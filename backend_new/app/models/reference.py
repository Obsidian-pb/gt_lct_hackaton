from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScenarioStatus(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Статусы учебных сценариев (окно 31 ТЗ)."""

    __tablename__ = "scenario_statuses"
    __table_args__ = {"schema": "reference"}

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class ApplicantStatus(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Статусы заявителя (окно 32 ТЗ): участник, очевидец, родственник."""

    __tablename__ = "applicant_statuses"
    __table_args__ = {"schema": "reference"}

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class TrainingRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Роли обучающихся при проведении тренировок (окно 35 ТЗ).

    - operator_112 — Оператор-112;
    - dispatcher_dds — Диспетчер ДДС;
    - service_dispatcher — Диспетчер службы (служба задаётся при назначении).
    """

    __tablename__ = "training_roles"
    __table_args__ = (
        CheckConstraint(
            "code IN ('operator_112', 'dispatcher_dds', 'service_dispatcher')",
            name="code_values",
        ),
        {"schema": "reference"},
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )