"""content: учебные задачи, эталоны, сценарии, методические материалы

Revision ID: 0004_content
Revises: 0003_reference
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_content"
down_revision: Union[str, None] = "0003_reference"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS content")

    op.create_table(
        "study_tasks",
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
        sa.Column("difficulty", sa.SmallInteger(), nullable=False),
        sa.Column("caller_message", sa.Text(), nullable=False),
        sa.Column("aon_phone", sa.String(length=32), nullable=True),
        sa.Column("provided_phone", sa.String(length=32), nullable=True),
        sa.Column("scene_phone", sa.String(length=32), nullable=True),
        sa.Column("caller_full_name", sa.String(length=255), nullable=True),
        sa.Column("applicant_status_id", sa.Uuid(), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("federal_subject", sa.String(length=255), nullable=True),
        sa.Column("locality", sa.String(length=255), nullable=True),
        sa.Column("address_object", sa.String(length=255), nullable=True),
        sa.Column("administrative_district", sa.String(length=255), nullable=True),
        sa.Column("district", sa.String(length=255), nullable=True),
        sa.Column("street", sa.String(length=255), nullable=True),
        sa.Column("house", sa.String(length=32), nullable=True),
        sa.Column("building", sa.String(length=32), nullable=True),
        sa.Column("structure", sa.String(length=32), nullable=True),
        sa.Column("apartment", sa.String(length=32), nullable=True),
        sa.Column("entrance", sa.String(length=32), nullable=True),
        sa.Column("floor", sa.String(length=32), nullable=True),
        sa.Column("intercom_code", sa.String(length=64), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("descriptive_address", sa.Text(), nullable=True),
        sa.Column("incident_description", sa.Text(), nullable=True),
        sa.Column(
            "has_victims", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "no_scene_refusal",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "no_access", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "no_contact", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "call_dropped", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("event_class_id", sa.Uuid(), nullable=True),
        sa.Column(
            "extra_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("main_service_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "difficulty BETWEEN 1 AND 5", name=op.f("ck_study_tasks_difficulty_range")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'review', 'approved', 'rejected', 'archived')",
            name=op.f("ck_study_tasks_status_values"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(extra_fields) = 'object'",
            name=op.f("ck_study_tasks_extra_fields_object"),
        ),
        sa.ForeignKeyConstraint(
            ["applicant_status_id"],
            ["reference.applicant_statuses.id"],
            name=op.f("fk_study_tasks_applicant_status_id_applicant_statuses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["auth.users.id"],
            name=op.f("fk_study_tasks_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth.users.id"],
            name=op.f("fk_study_tasks_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["event_class_id"],
            ["catalog.event_classes.id"],
            name=op.f("fk_study_tasks_event_class_id_event_classes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["main_service_id"],
            ["catalog.services.id"],
            name=op.f("fk_study_tasks_main_service_id_services"),
            ondelete="SET NULL",
        ),
        sa.Index(
            "ix_study_tasks_lookup",
            "difficulty",
            "status",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_tasks")),
        schema="content",
    )

    op.create_table(
        "task_etalons",
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
        sa.Column("study_task_id", sa.Uuid(), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "field_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'", name=op.f("ck_task_etalons_content_object")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(field_schema) = 'array'",
            name=op.f("ck_task_etalons_field_schema_array"),
        ),
        sa.ForeignKeyConstraint(
            ["study_task_id"],
            ["content.study_tasks.id"],
            name=op.f("fk_task_etalons_study_task_id_study_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_etalons")),
        sa.UniqueConstraint("study_task_id", name=op.f("uq_task_etalons_study_task_id")),
        schema="content",
    )

    op.create_table(
        "study_task_services",
        sa.Column("study_task_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["catalog.services.id"],
            name=op.f("fk_study_task_services_service_id_services"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["study_task_id"],
            ["content.study_tasks.id"],
            name=op.f("fk_study_task_services_study_task_id_study_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "study_task_id", "service_id", name=op.f("pk_study_task_services")
        ),
        schema="content",
    )

    op.create_table(
        "scenarios",
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
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scenario_status_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["auth.users.id"],
            name=op.f("fk_scenarios_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth.users.id"],
            name=op.f("fk_scenarios_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_status_id"],
            ["reference.scenario_statuses.id"],
            name=op.f("fk_scenarios_scenario_status_id_scenario_statuses"),
            ondelete="SET NULL",
        ),
        sa.Index(
            "ix_scenarios_lookup",
            "scenario_status_id",
            postgresql_where=sa.text("deleted_at IS NULL"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenarios")),
        schema="content",
    )

    op.create_table(
        "scenario_tasks",
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("study_task_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["content.scenarios.id"],
            name=op.f("fk_scenario_tasks_scenario_id_scenarios"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["study_task_id"],
            ["content.study_tasks.id"],
            name=op.f("fk_scenario_tasks_study_task_id_study_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "scenario_id", "study_task_id", name=op.f("pk_scenario_tasks")
        ),
        schema="content",
    )

    op.create_table(
        "study_materials",
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
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("file_type", sa.String(length=64), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["auth.users.id"],
            name=op.f("fk_study_materials_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_materials")),
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("study_materials", schema="content")
    op.drop_table("scenario_tasks", schema="content")
    op.drop_table("scenarios", schema="content")
    op.drop_table("study_task_services", schema="content")
    op.drop_table("task_etalons", schema="content")
    op.drop_table("study_tasks", schema="content")
    op.execute("DROP SCHEMA IF EXISTS content")