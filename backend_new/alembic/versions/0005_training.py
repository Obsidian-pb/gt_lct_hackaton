"""training: тренировки, участники, сессии, карточки происшествий

Revision ID: 0005_training
Revises: 0004_content
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005_training"
down_revision: Union[str, None] = "0004_content"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS training")

    op.create_table(
        "trainings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'prepared'"), nullable=False
        ),
        sa.Column(
            "card_time_limit_seconds",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "difficulty IN ('low', 'medium', 'high', 'adaptive')",
            name=op.f("ck_trainings_difficulty_values"),
        ),
        sa.CheckConstraint(
            "mode IN ('training', 'testing')", name=op.f("ck_trainings_mode_values")
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'active', 'finished')",
            name=op.f("ck_trainings_status_values"),
        ),
        sa.CheckConstraint(
            "card_time_limit_seconds > 0", name=op.f("ck_trainings_card_time_limit_positive")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth.users.id"],
            name=op.f("fk_trainings_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.Index(
            "ix_trainings_lookup",
            "status",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trainings")),
        schema="training",
    )

    op.create_table(
        "training_scenarios",
        sa.Column("training_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["content.scenarios.id"],
            name=op.f("fk_training_scenarios_scenario_id_scenarios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["training_id"],
            ["training.trainings.id"],
            name=op.f("fk_training_scenarios_training_id_trainings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "training_id", "scenario_id", name=op.f("pk_training_scenarios")
        ),
        schema="training",
    )

    op.create_table(
        "training_participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("training_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("training_role_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["catalog.services.id"],
            name=op.f("fk_training_participants_service_id_services"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["training_id"],
            ["training.trainings.id"],
            name=op.f("fk_training_participants_training_id_trainings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["training_role_id"],
            ["reference.training_roles.id"],
            name=op.f("fk_training_participants_training_role_id_training_roles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_training_participants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_participants")),
        sa.UniqueConstraint(
            "training_id", "user_id", name=op.f("uq_training_participants_training_id")
        ),
        schema="training",
    )

    op.create_table(
        "training_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("training_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'finished')",
            name=op.f("ck_training_sessions_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["training_id"],
            ["training.trainings.id"],
            name=op.f("fk_training_sessions_training_id_trainings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_training_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.Index("ix_training_sessions_user_status", "user_id", "status"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_sessions")),
        schema="training",
    )

    op.create_table(
        "incident_cards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("study_task_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("event_class_id", sa.Uuid(), nullable=True),
        sa.Column("main_service_id", sa.Uuid(), nullable=True),
        sa.Column("machine_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("ai_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("final_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "machine_eval_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ai_eval_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("evaluated_by", sa.Uuid(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("routed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "sequence_number > 0", name=op.f("ck_incident_cards_sequence_positive")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'accepted', 'routed', 'processed')",
            name=op.f("ck_incident_cards_status_values"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'", name=op.f("ck_incident_cards_content_object")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(machine_eval_details) = 'object'",
            name=op.f("ck_incident_cards_machine_eval_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(ai_eval_details) = 'object'",
            name=op.f("ck_incident_cards_ai_eval_object"),
        ),
        sa.CheckConstraint(
            "machine_score IS NULL OR (machine_score >= 0 AND machine_score <= 100)",
            name=op.f("ck_incident_cards_machine_score_range"),
        ),
        sa.CheckConstraint(
            "ai_score IS NULL OR (ai_score >= 0 AND ai_score <= 100)",
            name=op.f("ck_incident_cards_ai_score_range"),
        ),
        sa.CheckConstraint(
            "final_score IS NULL OR (final_score >= 0 AND final_score <= 100)",
            name=op.f("ck_incident_cards_final_score_range"),
        ),
        sa.ForeignKeyConstraint(
            ["event_class_id"],
            ["catalog.event_classes.id"],
            name=op.f("fk_incident_cards_event_class_id_event_classes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["evaluated_by"],
            ["auth.users.id"],
            name=op.f("fk_incident_cards_evaluated_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["main_service_id"],
            ["catalog.services.id"],
            name=op.f("fk_incident_cards_main_service_id_services"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["training.training_sessions.id"],
            name=op.f("fk_incident_cards_session_id_training_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["study_task_id"],
            ["content.study_tasks.id"],
            name=op.f("fk_incident_cards_study_task_id_study_tasks"),
            ondelete="RESTRICT",
        ),
        sa.Index("ix_incident_cards_session_seq", "session_id", "sequence_number"),
        sa.Index("ix_incident_cards_status", "status"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_cards")),
        sa.UniqueConstraint(
            "session_id", "sequence_number", name=op.f("uq_incident_cards_session_id")
        ),
        schema="training",
    )

    op.create_table(
        "card_services",
        sa.Column("card_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["training.incident_cards.id"],
            name=op.f("fk_card_services_card_id_incident_cards"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["catalog.services.id"],
            name=op.f("fk_card_services_service_id_services"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("card_id", "service_id", name=op.f("pk_card_services")),
        schema="training",
    )


def downgrade() -> None:
    op.drop_table("card_services", schema="training")
    op.drop_table("incident_cards", schema="training")
    op.drop_table("training_sessions", schema="training")
    op.drop_table("training_participants", schema="training")
    op.drop_table("training_scenarios", schema="training")
    op.drop_table("trainings", schema="training")
    op.execute("DROP SCHEMA IF EXISTS training")