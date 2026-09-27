from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token
from app.db.session import get_session
from app.models.auth import User

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Недействительные учётные данные",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    if credentials is None:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise _UNAUTHORIZED
    if payload.get("type") != "access":
        raise _UNAUTHORIZED
    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise _UNAUTHORIZED

    result = await session.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str):
    """Фабрика зависимостей: доступ только пользователям с указанными ролями."""

    async def checker(user: CurrentUser) -> User:
        user_role_codes = {role.code for role in user.roles}
        if not user_role_codes.intersection(roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения операции",
            )
        return user

    return checker