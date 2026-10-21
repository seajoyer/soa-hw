from fastapi import Request
from sqlalchemy import select

from app.auth import require_role
from app.db import SessionLocal
from app.errors import validation_error
from app.generated.main import PromoCodesApi
from app.generated.models import PromoCodeCreate, PromoCodeResponse, UserRole
from app.orm import PromoCode


class PromoCodeService(PromoCodesApi):
    def create_promo_code(self, request: Request, body: PromoCodeCreate) -> PromoCodeResponse:
        require_role(request, UserRole.SELLER, UserRole.ADMIN)
        if body.valid_from > body.valid_until:
            raise validation_error({"valid_until": ["Must not be earlier than valid_from"]})
        with SessionLocal.begin() as session:
            if session.scalar(select(PromoCode.id).where(PromoCode.code == body.code)) is not None:
                raise validation_error({"code": ["Promo code already exists"]})
            promo_code = PromoCode(**body.model_dump())
            session.add(promo_code)
            session.flush()
            session.refresh(promo_code)
            return PromoCodeResponse.model_validate(promo_code, from_attributes=True)
