from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.repositories.users import UserRepository
from app.schemas.users import (
    RoleListItem,
    UserCreate,
    UserOut,
    UserRoleAssign,
    UserUpdate,
)
from app.services.users import UserService

router = APIRouter()

admin_only = require_roles("system_admin", "admin")


@router.get("", response_model=list[UserOut], summary="Список пользователей (окно 12 ТЗ)")
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(admin_only)],
) -> list[UserOut]:
    users = await UserRepository(session).list_users()
    return [UserOut.model_validate(u) for u in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Создание пользователя")
async def create_user(
    payload: UserCreate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(admin_only)],
) -> UserOut:
    user = await UserService(session).create_user(payload, current_user.id)
    return UserOut.model_validate(user)


@router.get("/roles", response_model=list[RoleListItem], summary="Список ролей")
async def list_roles(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(admin_only)],
) -> list[RoleListItem]:
    roles = await UserRepository(session).list_roles()
    return [RoleListItem.model_validate(r) for r in roles]


@router.get("/{user_id}", response_model=UserOut, summary="Карточка пользователя (окно 13 ТЗ)")
async def get_user(
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(admin_only)],
) -> UserOut:
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден"
        )
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut, summary="Изменение пользователя")
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(admin_only)],
) -> UserOut:
    user = await UserService(session).update_user(user_id, payload, current_user.id)
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удаление пользователя")
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(admin_only)],
) -> None:
    await UserService(session).delete_user(user_id, current_user.id)


@router.put("/{user_id}/roles", response_model=UserOut, summary="Назначение ролей")
async def assign_roles(
    user_id: UUID,
    payload: UserRoleAssign,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(admin_only)],
) -> UserOut:
    user = await UserService(session).assign_roles(
        user_id, payload.role_codes, current_user.id
    )
    return UserOut.model_validate(user)