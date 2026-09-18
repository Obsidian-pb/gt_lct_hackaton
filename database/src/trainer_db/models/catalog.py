from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trainer_db.models.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    retention_check,
)


class EventClass(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    __tablename__ = "event_classes"
    __table_args__ = (retention_check(), {"schema": "catalog"})

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Service(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    __tablename__ = "services"
    __table_args__ = (retention_check(), {"schema": "catalog"})

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
