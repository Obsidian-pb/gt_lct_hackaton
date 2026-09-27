from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.content import Scenario

# --- Связующие таблицы -------------------------------------------------------

training_scenarios = Table(
    "training_scenarios",
    Base.metadata,
    Column(
        "training_id",
        ForeignKey("training.trainings.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "scenario_id",
        ForeignKey("content.scenarios.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "sort_order",
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    ),
    schema="training",
)

card_services = Table(
    "card_services",
    Base.metadata,
    Column(
        "card_id",
        ForeignKey("training.incident_cards.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        ForeignKey("catalog.services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="training",
)


class Training(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    """Тренировка (окно 11 ТЗ): сценарии + обучающиеся с ролями."""

    __tablename__ = "trainings"
    __table_args__ = (
        CheckConstraint(
            "difficulty IN ('low', 'medium', 'high', 'adaptive')",
            name="difficulty_values",
        ),
        CheckConstraint(
            "mode IN ('training', 'testing')", name="mode_values"
        ),
        CheckConstraint(
            "status IN ('prepared', 'active', 'finished')", name="status_values"
        ),
        CheckConstraint(
            "card_time_limit_seconds > 0", name="card_time_limit_positive"
        ),
        Index(
            "ix_trainings_lookup",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "training"},
    )

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="prepared", server_default="prepared"
    )
    # Норматив времени на одну карточку, секунды (по умолчанию 30)
    card_time_limit_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default=text("30")
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )

    scenarios: Mapped[list[Scenario]] = relationship(
        secondary=training_scenarios,
        lazy="selectin",
    )
    participants: Mapped[list[TrainingParticipant]] = relationship(
        back_populates="training",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TrainingParticipant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Обучающийся, назначенный на тренировку, с ролью (окно 11 ТЗ)."""

    __tablename__ = "training_participants"
    __table_args__ = (
        UniqueConstraint("training_id", "user_id"),
        # Требование service_id для роли service_dispatcher проверяется в сервисном слое
        {"schema": "training"},
    )

    training_id: Mapped[UUID] = mapped_column(
        ForeignKey("training.trainings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    training_role_id: Mapped[UUID] = mapped_column(
        ForeignKey("reference.training_roles.id", ondelete="RESTRICT"), nullable=False
    )
    # Обязательна для роли service_dispatcher (Диспетчер службы)
    service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.services.id", ondelete="SET NULL")
    )

    training: Mapped[Training] = relationship(back_populates="participants")


class TrainingSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Фактическое прохождение обучающимся тренировки в эмуляторе."""

    __tablename__ = "training_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'finished')", name="status_values"
        ),
        Index("ix_training_sessions_user_status", "user_id", "status"),
        {"schema": "training"},
    )

    training_id: Mapped[UUID] = mapped_column(
        ForeignKey("training.trainings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncidentCard(UUIDPrimaryKeyMixin, Base):
    """Карточка происшествия (окно 14 ТЗ), заполняемая обучающимся.

    Содержимое карточки хранится в JSONB (content); типизированы только
    метаданные, необходимые для фильтрации, отчётов и жизненного цикла.
    """

    __tablename__ = "incident_cards"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence_number"),
        CheckConstraint("sequence_number > 0", name="sequence_positive"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'accepted', 'routed', 'processed')",
            name="status_values",
        ),
        CheckConstraint("jsonb_typeof(content) = 'object'", name="content_object"),
        CheckConstraint("jsonb_typeof(machine_eval_details) = 'object'", name="machine_eval_object"),
        CheckConstraint("jsonb_typeof(ai_eval_details) = 'object'", name="ai_eval_object"),
        CheckConstraint(
            "machine_score IS NULL OR (machine_score >= 0 AND machine_score <= 100)",
            name="machine_score_range",
        ),
        CheckConstraint(
            "ai_score IS NULL OR (ai_score >= 0 AND ai_score <= 100)",
            name="ai_score_range",
        ),
        CheckConstraint(
            "final_score IS NULL OR (final_score >= 0 AND final_score <= 100)",
            name="final_score_range",
        ),
        Index("ix_incident_cards_session_seq", "session_id", "sequence_number"),
        Index("ix_incident_cards_status", "status"),
        {"schema": "training"},
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("training.training_sessions.id", ondelete="CASCADE"), nullable=False
    )
    study_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.study_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Жизненный цикл: draft -> submitted -> accepted -> routed -> processed
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )

    # Заполненное содержимое карточки (JSONB + Pydantic-валидация на уровне API)
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Типизированные метаданные для фильтров и отчётов.
    # Классификация копируется из учебной задачи при приёме вызова.
    event_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_types.id", ondelete="SET NULL")
    )
    event_feature_1_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_features_1.id", ondelete="SET NULL")
    )
    event_feature_2_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_features_2.id", ondelete="SET NULL")
    )
    event_feature_3_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_features_3.id", ondelete="SET NULL")
    )
    event_class_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_classes.id", ondelete="SET NULL")
    )
    main_service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.services.id", ondelete="SET NULL")
    )

    # Оценки: машинная, ИИ, итоговая (0-100)
    machine_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    ai_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    final_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    machine_eval_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ai_eval_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    evaluated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Тайминги
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    routed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)