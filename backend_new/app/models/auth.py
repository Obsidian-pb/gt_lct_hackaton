from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# --- Связующие таблицы -------------------------------------------------------

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        ForeignKey("auth.roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="auth",
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        ForeignKey("auth.roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        ForeignKey("auth.permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="auth",
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    """Пользователь системы (карточка пользователя, окно 13 ТЗ)."""

    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))

    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(32))

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users"
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Роль пользователя (RBAC). Системные роли: system_admin, admin, teacher, student."""

    __tablename__ = "roles"
    __table_args__ = {"schema": "auth"}

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    users: Mapped[list[User]] = relationship(
        secondary=user_roles, back_populates="roles"
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Отдельное разрешение (RBAC)."""

    __tablename__ = "permissions"
    __table_args__ = {"schema": "auth"}

    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


# Типы для переиспользования в других моделях
UserID = UUID
RoleID = UUID