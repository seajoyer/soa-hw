import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.db import SessionLocal
from app.errors import ApiError, validation_error
from app.generated.main import AuthApi
from app.generated.models import (
    AccessToken,
    ErrorCode,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    TokenType,
    UserResponse,
    UserRole,
)
from app.orm import User

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)
BCRYPT_MAX_BYTES = 72


@dataclass(frozen=True)
class Principal:
    id: UUID
    role: UserRole


def _password_bytes(password: str) -> bytes:
    return password.encode()[:BCRYPT_MAX_BYTES]


def _issue_token(user: User, token_type: str, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "role": user.role, "type": token_type, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str, token_type: str) -> Principal:
    payload = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "role", "type", "iat", "exp"]},
    )
    if payload["type"] != token_type:
        raise jwt.InvalidTokenError(f"Expected {token_type} token")
    try:
        return Principal(id=UUID(payload["sub"]), role=UserRole(payload["role"]))
    except ValueError as error:
        raise jwt.InvalidTokenError(str(error)) from error


_bearer = HTTPBearer(auto_error=False)


async def authenticate(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if credentials is None:
        raise ApiError(401, ErrorCode.TOKEN_INVALID, "Access token is missing")
    try:
        request.state.principal = _decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError:
        raise ApiError(401, ErrorCode.TOKEN_EXPIRED, "Access token has expired")
    except jwt.InvalidTokenError:
        raise ApiError(401, ErrorCode.TOKEN_INVALID, "Access token is invalid")


def require_role(request: Request, *roles: UserRole) -> Principal:
    principal: Principal = request.state.principal
    if principal.role not in roles:
        raise ApiError(
            403,
            ErrorCode.ACCESS_DENIED,
            f"Role {principal.role} is not allowed to perform this operation",
            {"role": principal.role},
        )
    return principal


class AuthService(AuthApi):
    def register(self, request: Request, body: RegisterRequest) -> UserResponse:
        with SessionLocal.begin() as session:
            if session.scalar(select(User.id).where(User.username == body.username)) is not None:
                raise validation_error({"username": ["Username is already taken"]})
            user = User(
                username=body.username,
                password_hash=bcrypt.hashpw(_password_bytes(body.password), bcrypt.gensalt()).decode(),
                role=body.role,
            )
            session.add(user)
            session.flush()
            session.refresh(user)
            return UserResponse.model_validate(user, from_attributes=True)

    def login(self, request: Request, body: LoginRequest) -> TokenPair:
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.username == body.username))
        if user is None or not bcrypt.checkpw(_password_bytes(body.password), user.password_hash.encode()):
            raise ApiError(401, ErrorCode.INVALID_CREDENTIALS, "Invalid username or password")
        return TokenPair(
            access_token=_issue_token(user, "access", ACCESS_TOKEN_TTL),
            refresh_token=_issue_token(user, "refresh", REFRESH_TOKEN_TTL),
            token_type=TokenType.Bearer,
        )

    def refresh(self, request: Request, body: RefreshRequest) -> AccessToken:
        try:
            principal = _decode_token(body.refresh_token, "refresh")
        except jwt.InvalidTokenError:
            raise ApiError(401, ErrorCode.REFRESH_TOKEN_INVALID, "Refresh token is invalid or expired")
        with SessionLocal() as session:
            user = session.get(User, principal.id)
        if user is None:
            raise ApiError(401, ErrorCode.REFRESH_TOKEN_INVALID, "Refresh token is invalid or expired")
        return AccessToken(access_token=_issue_token(user, "access", ACCESS_TOKEN_TTL), token_type=TokenType.Bearer)
