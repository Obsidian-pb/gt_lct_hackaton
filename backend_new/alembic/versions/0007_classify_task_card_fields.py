"""Классификация по компонентам + схема доп. полей учебной задачи

- content.study_tasks: + event_type_id, event_feature_1_id, event_feature_2_id, event_feature_3_id
- training.incident_cards: + event_type_id, event_feature_1_id, event_feature_2_id, event_feature_3_id
- content.task_extra_field_schemas: новая таблица — схема дополнительных полей
  учебной задачи (значения доп. полей хранятся в study_tasks.extra_fields и в
  содержимом карточки incident_cards.content).

Revision ID: 0007_classify_task_card_fields
Revises: 0006_audit_system
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007_classify_task_card_fields"
down_revision: Union[str, None] = "0006_audit_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CLASSIFICATION_COLUMNS = [
    # Имя колонки -> имя таблицы-референта (схема передаётся отдельно,
    # в referent_schema="catalog", поэтому префикс здесь не нужен).
    ("event_type_id", "event_types"),
    ("event_feature_1_id", "event_features_1"),
    ("event_feature_2_id", "event_features_2"),
    ("event_feature_3_id", "event_features_3"),
]


def _add_classification_columns(table: str, schema: str) -> None:
    for column, ref_table in _CLASSIFICATION_COLUMNS:
        op.add_column(
            table,
            sa.Column(column, sa.Uuid(), nullable=True),
            schema=schema,
        )
        op.create_foreign_key(
            op.f(f"fk_{table}_{column}"),
            table,
            ref_table,
            [column],
            ["id"],
            source_schema=schema,
            referent_schema="catalog",
            ondelete="SET NULL",
        )


def _drop_classification_columns(table: str, schema: str) -> None:
    for column, _ in _CLASSIFICATION_COLUMNS:
        op.drop_constraint(
            op.f(f"fk_{table}_{column}"),
            table,
            type_="foreignkey",
            schema=schema,
        )
        op.drop_column(table, column, schema=schema)


def upgrade() -> None:
    # --- Классификация по компонентам (Группа + Признаки 1-3) ---
    _add_classification_columns("study_tasks", "content")
    _add_classification_columns("incident_cards", "training")

    # --- Схема дополнительных полей учебной задачи ---
    op.create_table(
        "task_extra_field_schemas",
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
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("field_type", sa.String(length=16), nullable=False),
        sa.Column(
            "required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "field_type IN ('text', 'number', 'boolean', 'select', 'date')",
            name=op.f("ck_task_extra_field_schemas_field_type_values"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array'",
            name=op.f("ck_task_extra_field_schemas_options_array"),
        ),
        sa.ForeignKeyConstraint(
            ["study_task_id"],
            ["content.study_tasks.id"],
            name=op.f("fk_task_extra_field_schemas_study_task_id_study_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_extra_field_schemas")),
        sa.UniqueConstraint(
            "study_task_id",
            "code",
            name=op.f("uq_task_extra_field_schemas_study_task_code"),
        ),
        schema="content",
    )


def downgrade() -> None:
    op.drop_table("task_extra_field_schemas", schema="content")
    _drop_classification_columns("incident_cards", "training")
    _drop_classification_columns("study_tasks", "content")