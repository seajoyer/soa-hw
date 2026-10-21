from fastapi import Depends, FastAPI

from app.auth import AuthService, authenticate
from app.errors import register_error_handlers
from app.orders import OrderService
from app.products import ProductService
from app.promo_codes import PromoCodeService
from app.request_logging import register_request_logging

app = FastAPI(title="Marketplace API")
register_error_handlers(app)
register_request_logging(app)
app.include_router(AuthService().router())
for service in (ProductService(), OrderService(), PromoCodeService()):
    app.include_router(service.router(), dependencies=[Depends(authenticate)])
