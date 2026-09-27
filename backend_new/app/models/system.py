from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SystemSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Ключ-значение системных настроек (ИИ, БД, журналирование и т.д.)."""

    __tablename__ = "system_settings"
    __table_args__ = {"schema": "system"}

    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    value: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )