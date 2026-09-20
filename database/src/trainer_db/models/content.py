from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trainer_db.models.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    retention_check,
)


event_template_services = Table(
    "event_template_services",
    Base.metadata,
    Column(
        "event_template_id",
        ForeignKey("content.event_templates.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        ForeignKey("catalog.services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="content",
)


exercise_services = Table(
    "exercise_services",
    Base.metadata,
    Column(
        "exercise_id",
        ForeignKey("content.exercises.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        ForeignKey("catalog.services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="content",
)


class EventTemplate(
    UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base
):
    __tablename__ = "event_templates"
    __table_args__ = (
        retention_check(),
        CheckConstraint(
            "status IN ('draft', 'review', 'approved', 'archived')",
            name="status_values",
        ),
        CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings_object"),
        Index(
            "ix_event_templates_active",
            "event_class_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "content"},
    )

    event_class_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_classes.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    generation_instructions: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )


class Exercise(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    __tablename__ = "exercises"
    __table_args__ = (
        retention_check(),
        CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')", name="difficulty_values"
        ),
        CheckConstraint(
            "status IN ('draft', 'review', 'approved', 'rejected', 'archived')",
            name="status_values",
        ),
        CheckConstraint("source IN ('ai_generated', 'manual')", name="source_values"),
        Index(
            "ix_exercises_bank_lookup",
            "difficulty",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "content"},
    )

    event_template_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.event_templates.id", ondelete="CASCADE"), nullable=False
    )
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ai_generated", server_default="ai_generated"
    )
    active_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "content.exercise_revisions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_exercises_active_revision",
        ),
        nullable=True,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    revisions: Mapped[list[ExerciseRevision]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        foreign_keys="ExerciseRevision.exercise_id",
    )


class ExerciseRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "exercise_revisions"
    __table_args__ = (
        UniqueConstraint("exercise_id", "revision_number"),
        CheckConstraint("revision_number > 0", name="revision_positive"),
        CheckConstraint(
            "review_status IN ('draft', 'review', 'approved', 'rejected', 'superseded')",
            name="review_status_values",
        ),
        CheckConstraint("jsonb_typeof(field_schema) = 'array'", name="field_schema_array"),
        CheckConstraint("jsonb_typeof(source_payload) = 'object'", name="source_payload_object"),
        CheckConstraint("jsonb_typeof(trainee_card) = 'object'", name="trainee_card_object"),
        CheckConstraint("jsonb_typeof(ethalon_payload) = 'object'", name="ethalon_payload_object"),
        Index("ix_exercise_revisions_source_gin", "source_payload", postgresql_using="gin"),
        Index("ix_exercise_revisions_ethalon_gin", "ethalon_payload", postgresql_using="gin"),
        {"schema": "content"},
    )

    exercise_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.exercises.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    field_schema: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    trainee_card: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    ethalon_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    change_comment: Mapped[str | None] = mapped_column(Text)
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    exercise: Mapped[Exercise] = relationship(
        back_populates="revisions", foreign_keys=[exercise_id]
    )
