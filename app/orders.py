import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Principal, require_role
from app.db import SessionLocal
from app.errors import ApiError, validation_error
from app.generated.main import OrdersApi
from app.generated.models import (
    DiscountType,
    ErrorCode,
    OrderCreate,
    OrderItemRequest,
    OrderResponse,
    OrderStatus,
    OrderUpdate,
    ProductStatus,
    UserRole,
)
from app.orm import Order, OrderItem, Product, PromoCode, UserOperation

RATE_LIMIT = timedelta(minutes=int(os.environ["ORDER_RATE_LIMIT_MINUTES"]))
MAX_PERCENTAGE_DISCOUNT = Decimal(70)
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999.99")

ACTIVE_STATUSES = (OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING)

TRANSITIONS = {
    OrderStatus.CREATED: {OrderStatus.PAYMENT_PENDING, OrderStatus.CANCELED},
    OrderStatus.PAYMENT_PENDING: {OrderStatus.PAID, OrderStatus.CANCELED},
    OrderStatus.PAID: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELED: set(),
}


def _to_response(order: Order) -> OrderResponse:
    return OrderResponse.model_validate(order, from_attributes=True)


def _lock_user(session: Session, user_id: UUID) -> None:
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(user_id)))))


def _check_rate_limit(session: Session, user_id: UUID, operation_type: str) -> None:
    last_operation_at = session.scalar(
        select(UserOperation.created_at)
        .where(UserOperation.user_id == user_id, UserOperation.operation_type == operation_type)
        .order_by(UserOperation.created_at.desc())
        .limit(1)
    )
    if last_operation_at is not None and datetime.now(timezone.utc) - last_operation_at < RATE_LIMIT:
        raise ApiError(
            429,
            ErrorCode.ORDER_LIMIT_EXCEEDED,
            f"{operation_type} is allowed once per {RATE_LIMIT}",
        )


def _get_owned_order(session: Session, order_id: UUID, principal: Principal) -> Order:
    order = session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise ApiError(404, ErrorCode.ORDER_NOT_FOUND, f"Order {order_id} not found", {"order_id": str(order_id)})
    if principal.role != UserRole.ADMIN and order.user_id != principal.id:
        raise ApiError(403, ErrorCode.ORDER_OWNERSHIP_VIOLATION, "Order belongs to another user")
    return order


def _transition(order: Order, target: OrderStatus) -> None:
    if target not in TRANSITIONS[order.status]:
        raise ApiError(
            409,
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot change order status from {order.status} to {target}",
            {"from": order.status, "to": target},
        )
    order.status = target


def _lock_products(session: Session, product_ids: set[UUID]) -> dict[UUID, Product]:
    products = session.scalars(
        select(Product).where(Product.id.in_(product_ids)).order_by(Product.id).with_for_update()
    ).all()
    return {product.id: product for product in products}


def _reserve(products: dict[UUID, Product], items: list[OrderItemRequest]) -> list[OrderItem]:
    for item in items:
        product = products.get(item.product_id)
        if product is None:
            raise ApiError(
                404,
                ErrorCode.PRODUCT_NOT_FOUND,
                f"Product {item.product_id} not found",
                {"product_id": str(item.product_id)},
            )
        if product.status != ProductStatus.ACTIVE:
            raise ApiError(
                409,
                ErrorCode.PRODUCT_INACTIVE,
                f"Product {item.product_id} is not active",
                {"product_id": str(item.product_id), "status": product.status},
            )

    requested: dict[UUID, int] = defaultdict(int)
    for item in items:
        requested[item.product_id] += item.quantity

    shortages = [
        {
            "product_id": str(product_id),
            "requested_quantity": quantity,
            "available_stock": products[product_id].stock,
        }
        for product_id, quantity in requested.items()
        if products[product_id].stock < quantity
    ]
    if shortages:
        raise ApiError(409, ErrorCode.INSUFFICIENT_STOCK, "Insufficient stock", {"items": shortages})

    for product_id, quantity in requested.items():
        products[product_id].stock -= quantity

    return [
        OrderItem(
            product_id=item.product_id,
            quantity=item.quantity,
            price_at_order=products[item.product_id].price,
        )
        for item in items
    ]


def _release(products: dict[UUID, Product], items: list[OrderItem]) -> None:
    for item in items:
        products[item.product_id].stock += item.quantity


def _subtotal(items: list[OrderItem]) -> Decimal:
    subtotal = sum((item.price_at_order * item.quantity for item in items), Decimal(0))
    if subtotal > MAX_AMOUNT:
        raise validation_error({"items": [f"Order amount must not exceed {MAX_AMOUNT}"]})
    return subtotal


def _is_active(promo_code: PromoCode) -> bool:
    return promo_code.active and promo_code.valid_from <= datetime.now(timezone.utc) <= promo_code.valid_until


def _discount(promo_code: PromoCode, subtotal: Decimal) -> Decimal:
    if promo_code.discount_type == DiscountType.FIXED_AMOUNT:
        return min(promo_code.discount_value, subtotal)
    if promo_code.discount_value > MAX_PERCENTAGE_DISCOUNT:
        return Decimal(0)
    return (subtotal * promo_code.discount_value / 100).quantize(CENT, ROUND_HALF_UP)


def _apply_amounts(order: Order, subtotal: Decimal, discount: Decimal) -> None:
    order.discount_amount = discount
    order.total_amount = subtotal - discount


class OrderService(OrdersApi):
    def create_order(self, request: Request, body: OrderCreate) -> OrderResponse:
        user_id = require_role(request, UserRole.USER, UserRole.ADMIN).id
        with SessionLocal.begin() as session:
            _lock_user(session, user_id)
            _check_rate_limit(session, user_id, "CREATE_ORDER")

            active_order_id = session.scalar(
                select(Order.id).where(Order.user_id == user_id, Order.status.in_(ACTIVE_STATUSES)).limit(1)
            )
            if active_order_id is not None:
                raise ApiError(
                    409,
                    ErrorCode.ORDER_HAS_ACTIVE,
                    "User already has an active order",
                    {"order_id": str(active_order_id)},
                )

            products = _lock_products(session, {item.product_id for item in body.items})
            order = Order(user_id=user_id, status=OrderStatus.CREATED, items=_reserve(products, body.items))
            subtotal = _subtotal(order.items)
            discount = Decimal(0)

            if body.promo_code is not None:
                promo_code = session.scalar(
                    select(PromoCode).where(PromoCode.code == body.promo_code).with_for_update()
                )
                if (
                    promo_code is None
                    or not _is_active(promo_code)
                    or promo_code.current_uses >= promo_code.max_uses
                ):
                    raise ApiError(
                        422,
                        ErrorCode.PROMO_CODE_INVALID,
                        f"Promo code {body.promo_code} is invalid",
                        {"promo_code": body.promo_code},
                    )
                if subtotal < promo_code.min_order_amount:
                    raise ApiError(
                        422,
                        ErrorCode.PROMO_CODE_MIN_AMOUNT,
                        f"Order amount is below the minimum for promo code {body.promo_code}",
                        {"order_amount": str(subtotal), "min_order_amount": str(promo_code.min_order_amount)},
                    )
                discount = _discount(promo_code, subtotal)
                promo_code.current_uses += 1
                order.promo_code_id = promo_code.id

            _apply_amounts(order, subtotal, discount)
            session.add(order)
            session.add(UserOperation(user_id=user_id, operation_type="CREATE_ORDER"))
            session.flush()
            session.refresh(order)
            return _to_response(order)

    def get_order(self, request: Request, id: UUID) -> OrderResponse:
        principal = require_role(request, UserRole.USER, UserRole.ADMIN)
        with SessionLocal() as session:
            return _to_response(_get_owned_order(session, id, principal))

    def update_order(self, request: Request, id: UUID, body: OrderUpdate) -> OrderResponse:
        principal = require_role(request, UserRole.USER, UserRole.ADMIN)
        user_id = principal.id
        with SessionLocal.begin() as session:
            _lock_user(session, user_id)
            order = _get_owned_order(session, id, principal)
            if order.status != OrderStatus.CREATED:
                raise ApiError(
                    409,
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"Order in status {order.status} cannot be updated",
                    {"status": order.status},
                )
            _check_rate_limit(session, user_id, "UPDATE_ORDER")

            product_ids = {item.product_id for item in order.items} | {item.product_id for item in body.items}
            products = _lock_products(session, product_ids)
            _release(products, order.items)
            order.items = _reserve(products, body.items)
            subtotal = _subtotal(order.items)
            discount = Decimal(0)

            if order.promo_code_id is not None:
                promo_code = session.get(PromoCode, order.promo_code_id, with_for_update=True)
                if _is_active(promo_code) and subtotal >= promo_code.min_order_amount:
                    discount = _discount(promo_code, subtotal)
                else:
                    promo_code.current_uses -= 1
                    order.promo_code_id = None

            _apply_amounts(order, subtotal, discount)
            session.add(UserOperation(user_id=user_id, operation_type="UPDATE_ORDER"))
            session.flush()
            session.refresh(order)
            return _to_response(order)

    def cancel_order(self, request: Request, id: UUID) -> OrderResponse:
        principal = require_role(request, UserRole.USER, UserRole.ADMIN)
        with SessionLocal.begin() as session:
            order = _get_owned_order(session, id, principal)
            _transition(order, OrderStatus.CANCELED)

            products = _lock_products(session, {item.product_id for item in order.items})
            _release(products, order.items)

            if order.promo_code_id is not None:
                promo_code = session.get(PromoCode, order.promo_code_id, with_for_update=True)
                promo_code.current_uses -= 1

            session.flush()
            session.refresh(order)
            return _to_response(order)
