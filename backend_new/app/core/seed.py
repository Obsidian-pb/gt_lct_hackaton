from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.auth import Role, User

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"


async def seed_default_admin(session: AsyncSession) -> User | None:
    """Создаёт учётную запись администратора, если пользователей ещё нет."""
    exists = await session.scalar(
        select(User.id).where(User.username == DEFAULT_ADMIN_USERNAME).limit(1)
    )
    if exists:
        return None
    roles = list(
        (
            await session.execute(
                select(Role).where(Role.code.in_(["admin", "system_admin"]))
            )
        )
        .scalars()
        .all()
    )
    user = User(
        username=DEFAULT_ADMIN_USERNAME,
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        last_name="Администратор",
        first_name="Система",
        is_active=True,
    )
    user.roles = roles
    session.add(user)
    await session.commit()
    return user