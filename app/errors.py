from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError

from app.generated.models import ErrorCode, ErrorResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details


def _error_response(error: ApiError) -> JSONResponse:
    body = ErrorResponse(error_code=error.error_code, message=error.message, details=error.details)
    return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))


def validation_error(details: dict[str, list[str]]) -> ApiError:
    return ApiError(400, ErrorCode.VALIDATION_ERROR, "Request validation failed", details)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return _error_response(error)

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        details: dict[str, list[str]] = {}
        for violation in error.errors():
            location = violation["loc"][1:]
            if not location or violation["type"] == "json_invalid":
                location = violation["loc"][:1]
            field = ".".join(str(part) for part in location)
            details.setdefault(field, []).append(violation["msg"])
        return _error_response(validation_error(details))

    @app.exception_handler(DataError)
    def handle_data_error(request: Request, error: DataError) -> JSONResponse:
        return _error_response(validation_error({"request": ["Value is not supported by the database"]}))
