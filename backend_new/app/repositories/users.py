from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import Role, User


class UserRepository:
    """Доступ к данным пользователей и ролей (изоляция SQL-запросов)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.username == username, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_username_all(self, username: str) -> User | None:
        """Поиск без фильтра мягкого удаления — для проверки уникальности логина."""
        result = await self._session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def list_users(self) -> list[User]:
        result = await self._session.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.deleted_at.is_(None))
            .order_by(User.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_role(self, role_code: str) -> list[User]:
        """Пользователи с указанной ролью (окно 9 ТЗ — список обучающихся)."""
        result = await self._session.execute(
            select(User)
            .join(User.roles)
            .options(selectinload(User.roles))
            .where(User.deleted_at.is_(None), Role.code == role_code)
            .order_by(User.last_name, User.first_name)
        )
        return list(result.scalars().all())

    async def get_roles_by_codes(self, codes: list[str]) -> list[Role]:
        result = await self._session.execute(select(Role).where(Role.code.in_(codes)))
        return list(result.scalars().all())

    async def list_roles(self) -> list[Role]:
        result = await self._session.execute(select(Role).order_by(Role.name))
        return list(result.scalars().all())

    def add(self, user: User) -> None:
        self._session.add(user)