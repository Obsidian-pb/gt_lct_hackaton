from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trainer_db.models.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    retention_check,
)


class ScoringProfile(
    UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base
):
    __tablename__ = "scoring_profiles"
    __table_args__ = (
        retention_check(),
        {"schema": "training"},
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )


class ScoringRule(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scoring_rules"
    __table_args__ = (
        UniqueConstraint("profile_id", "difficulty"),
        CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')", name="difficulty_values"
        ),
        CheckConstraint(
            "correctness_threshold >= 0 AND correctness_threshold <= 100",
            name="threshold_range",
        ),
        CheckConstraint("half_life_seconds > 0", name="half_life_positive"),
        CheckConstraint(
            "min_time_factor >= 0 AND min_time_factor <= 1",
            name="min_time_factor_range",
        ),
        CheckConstraint("max_score > 0", name="max_score_positive"),
        {"schema": "training"},
    )

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("training.scoring_profiles.id", ondelete="CASCADE"), nullable=False
    )
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    correctness_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    half_life_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    min_time_factor: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)


class TrainingSession(
    UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base
):
    __tablename__ = "sessions"
    __table_args__ = (
        retention_check(),
        CheckConstraint("requested_card_count > 0", name="card_count_positive"),
        CheckConstraint(
            "starting_difficulty IN ('easy', 'medium', 'hard')",
            name="starting_difficulty_values",
        ),
        CheckConstraint(
            "current_difficulty IN ('easy', 'medium', 'hard')",
            name="current_difficulty_values",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'completed', 'cancelled')",
            name="status_values",
        ),
        CheckConstraint(
            "jsonb_typeof(scoring_snapshot) = 'object'",
            name="scoring_snapshot_object",
        ),
        Index(
            "ix_sessions_trainee_status",
            "trainee_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "training"},
    )

    trainee_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    teacher_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    scoring_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("training.scoring_profiles.id", ondelete="SET NULL")
    )
    requested_card_count: Mapped[int] = mapped_column(Integer, nullable=False)
    starting_difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    current_difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    scoring_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionCard(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "session_cards"
    __table_args__ = (
        UniqueConstraint("session_id", "sequence_number"),
        CheckConstraint("sequence_number > 0", name="sequence_positive"),
        CheckConstraint(
            "difficulty_snapshot IN ('easy', 'medium', 'hard')",
            name="difficulty_values",
        ),
        CheckConstraint(
            "status IN ('pending', 'shown', 'submitted', 'evaluated')",
            name="status_values",
        ),
        Index("ix_session_cards_session_sequence", "session_id", "sequence_number"),
        {"schema": "training"},
    )

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("training.sessions.id", ondelete="CASCADE"), nullable=False
    )
    exercise_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.exercise_revisions.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_snapshot: Mapped[str] = mapped_column(String(16), nullable=False)
    is_repeat: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class Answer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("session_card_id"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        {"schema": "training"},
    )

    session_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("training.session_cards.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class Evaluation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint("answer_id"),
        CheckConstraint(
            "accuracy_percent >= 0 AND accuracy_percent <= 100",
            name="accuracy_range",
        ),
        CheckConstraint(
            "threshold_percent >= 0 AND threshold_percent <= 100",
            name="threshold_range",
        ),
        CheckConstraint(
            "time_factor >= 0 AND time_factor <= 1", name="time_factor_range"
        ),
        CheckConstraint("accuracy_score >= 0", name="accuracy_score_nonnegative"),
        CheckConstraint("total_score >= 0", name="total_score_nonnegative"),
        CheckConstraint(
            "current_difficulty IN ('easy', 'medium', 'hard')",
            name="current_difficulty_values",
        ),
        CheckConstraint(
            "next_difficulty IN ('easy', 'medium', 'hard')",
            name="next_difficulty_values",
        ),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),
        CheckConstraint(
            "jsonb_typeof(scoring_rule_snapshot) = 'object'",
            name="scoring_rule_snapshot_object",
        ),
        {"schema": "training"},
    )

    answer_id: Mapped[UUID] = mapped_column(
        ForeignKey("training.answers.id", ondelete="CASCADE"), nullable=False
    )
    accuracy_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    threshold_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    time_factor: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    accuracy_score: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    total_score: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    current_difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    next_difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    scoring_rule_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
