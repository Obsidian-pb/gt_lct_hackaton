from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.auth import Role, User
from app.repositories.users import UserRepository
from app.schemas.users import UserCreate, UserUpdate
from app.services.audit import record_audit


class UserService:
    """Бизнес-логика управления пользователями."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)
        self._session = session

    async def create_user(self, data: UserCreate, actor_id: UUID) -> User:
        if await self._repo.get_by_username_all(data.username) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Пользователь с таким логином уже существует",
            )
        roles = await self._repo.get_roles_by_codes(data.role_codes)
        found_codes = {role.code for role in roles}
        unknown = set(data.role_codes) - found_codes
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Неизвестные роли: {', '.join(sorted(unknown))}",
            )

        user = User(
            username=data.username,
            email=data.email,
            password_hash=hash_password(data.password),
            last_name=data.last_name,
            first_name=data.first_name,
            middle_name=data.middle_name,
            phone=data.phone,
            is_active=True,
        )
        user.roles = roles
        self._repo.add(user)
        try:
            await record_audit(
                self._session,
                actor_id=actor_id,
                action="user.create",
                entity_type="user",
                entity_id=user.id,
                payload={"username": user.username, "roles": data.role_codes},
            )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Пользователь с таким логином уже существует",
            )
        return await self._require_user(user.id)

    async def update_user(self, user_id: UUID, data: UserUpdate, actor_id: UUID) -> User:
        user = await self._require_user(user_id)
        changes = data.model_dump(exclude_unset=True)
        password = changes.pop("password", None)
        for field, value in changes.items():
            setattr(user, field, value)
        if password:
            user.password_hash = hash_password(password)
        await record_audit(
            self._session,
            actor_id=actor_id,
            action="user.update",
            entity_type="user",
            entity_id=user_id,
        )
        await self._session.commit()
        return await self._require_user(user_id)

    async def delete_user(self, user_id: UUID, actor_id: UUID) -> None:
        """Мягкое удаление: помечаем deleted_at и purge_after."""
        user = await self._require_user(user_id)
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        user.deleted_at = now
        user.purge_after = now + timedelta(days=180)
        await record_audit(
            self._session,
            actor_id=actor_id,
            action="user.delete",
            entity_type="user",
            entity_id=user_id,
        )
        await self._session.commit()

    async def assign_roles(
        self, user_id: UUID, role_codes: list[str], actor_id: UUID
    ) -> User:
        user = await self._require_user(user_id)
        roles = await self._repo.get_roles_by_codes(role_codes)
        found_codes = {role.code for role in roles}
        unknown = set(role_codes) - found_codes
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Неизвестные роли: {', '.join(sorted(unknown))}",
            )
        user.roles = roles
        await record_audit(
            self._session,
            actor_id=actor_id,
            action="user.assign_roles",
            entity_type="user",
            entity_id=user_id,
            payload={"roles": role_codes},
        )
        await self._session.commit()
        return await self._require_user(user_id)

    async def _require_user(self, user_id: UUID) -> User:
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден",
            )
        return user