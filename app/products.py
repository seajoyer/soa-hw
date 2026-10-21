from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Principal, require_role
from app.db import SessionLocal
from app.errors import ApiError
from app.generated.main import ProductsApi
from app.generated.models import (
    ErrorCode,
    ProductCreate,
    ProductPage,
    ProductResponse,
    ProductStatus,
    ProductUpdate,
    UserRole,
)
from app.orm import Product


def _get_or_404(session: Session, id: UUID) -> Product:
    product = session.get(Product, id)
    if product is None:
        raise ApiError(404, ErrorCode.PRODUCT_NOT_FOUND, f"Product {id} not found", {"product_id": str(id)})
    return product


def _get_managed(session: Session, id: UUID, principal: Principal) -> Product:
    product = _get_or_404(session, id)
    if principal.role == UserRole.SELLER and product.seller_id != principal.id:
        raise ApiError(403, ErrorCode.ACCESS_DENIED, "Seller can manage only own products", {"product_id": str(id)})
    return product


def _to_response(product: Product) -> ProductResponse:
    return ProductResponse.model_validate(product, from_attributes=True)


class ProductService(ProductsApi):
    def create_product(self, request: Request, body: ProductCreate) -> ProductResponse:
        principal = require_role(request, UserRole.SELLER, UserRole.ADMIN)
        with SessionLocal() as session:
            product = Product(seller_id=principal.id, **body.model_dump())
            session.add(product)
            session.commit()
            session.refresh(product)
            return _to_response(product)

    def list_products(
        self,
        request: Request,
        page: int = 0,
        size: int = 20,
        status: ProductStatus | None = None,
        category: str | None = None,
    ) -> ProductPage:
        query = select(Product)
        if status is not None:
            query = query.where(Product.status == status)
        if category is not None:
            query = query.where(Product.category == category)
        with SessionLocal() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            products = session.scalars(
                query.order_by(Product.created_at, Product.id).offset(page * size).limit(size)
            ).all()
            return ProductPage(
                items=[_to_response(product) for product in products],
                totalElements=total,
                page=page,
                size=size,
            )

    def get_product(self, request: Request, id: UUID) -> ProductResponse:
        with SessionLocal() as session:
            return _to_response(_get_or_404(session, id))

    def update_product(self, request: Request, id: UUID, body: ProductUpdate) -> ProductResponse:
        principal = require_role(request, UserRole.SELLER, UserRole.ADMIN)
        with SessionLocal() as session:
            product = _get_managed(session, id, principal)
            for field, value in body.model_dump().items():
                setattr(product, field, value)
            session.commit()
            session.refresh(product)
            return _to_response(product)

    def delete_product(self, request: Request, id: UUID) -> None:
        principal = require_role(request, UserRole.SELLER, UserRole.ADMIN)
        with SessionLocal() as session:
            product = _get_managed(session, id, principal)
            product.status = ProductStatus.ARCHIVED
            session.commit()
