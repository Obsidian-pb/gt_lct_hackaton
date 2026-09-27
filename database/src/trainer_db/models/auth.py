from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Table, Text, Column, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trainer_db.models.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    retention_check,
)

if TYPE_CHECKING:
    from trainer_db.models.content import Exercise, ExerciseRevision, EventTemplate
    from trainer_db.models.training import ScoringProfile, TrainingSession


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


user_services = Table(
    "user_services",
    Base.metadata,
    Column("user_id", ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("catalog.services.id", ondelete="CASCADE"), primary_key=True),
    Column("assigned_by", ForeignKey("auth.users.id", ondelete="SET NULL")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    Index("ix_user_services_service_id", "service_id"),
    schema="auth",
)


class User(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    __tablename__ = "users"
    __table_args__ = (retention_check(), {"schema": "auth"})

    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles, back_populates="users"
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
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
    __tablename__ = "permissions"
    __table_args__ = {"schema": "auth"}

    code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )
