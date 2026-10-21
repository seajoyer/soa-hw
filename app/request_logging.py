import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request

MUTATING_METHODS = {"POST", "PUT", "DELETE"}
SENSITIVE_FIELDS = {"password", "refresh_token"}
MASK = "***"

logger = logging.getLogger("api")
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))
logger.propagate = False


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: MASK if key in SENSITIVE_FIELDS else _mask(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    return value


def _request_body(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return _mask(json.loads(raw))
    except ValueError:
        return raw.decode(errors="replace")


def register_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_request(request: Request, call_next):
        request_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        body = await request.body() if request.method in MUTATING_METHODS else None
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            principal = getattr(request.state, "principal", None)
            entry = {
                "request_id": request_id,
                "method": request.method,
                "endpoint": request.url.path,
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "user_id": str(principal.id) if principal else None,
                "timestamp": timestamp,
            }
            if body is not None:
                entry["request_body"] = _request_body(body)
            logger.info(json.dumps(entry, ensure_ascii=False))
