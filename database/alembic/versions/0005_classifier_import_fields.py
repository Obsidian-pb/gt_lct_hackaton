"""Prepare classifier tables for the official workbook import.

Revision ID: 0005_classifier_import_fields
Revises: 0004_rename_event_feature_1
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_classifier_import_fields"
down_revision: str | None = "0004_rename_event_feature_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_event_types_code_range"),
        "event_types",
        schema="catalog",
        type_="check",
    )
    op.create_check_constraint(
        "code_range",
        "event_types",
        "code BETWEEN 1 AND 99",
        schema="catalog",
    )

    op.alter_column(
        "event_features_2",
        "name",
        existing_type=sa.String(length=1024),
        nullable=True,
        schema="catalog",
    )
    op.alter_column(
        "event_features_3",
        "name",
        existing_type=sa.String(length=1024),
        nullable=True,
        schema="catalog",
    )

    for column_name in (
        "feature_1_label",
        "feature_2_label",
        "feature_3_label",
    ):
        op.add_column(
            "event_classes",
            sa.Column(column_name, sa.String(length=1024), nullable=True),
            schema="catalog",
        )


def downgrade() -> None:
    for column_name in (
        "feature_3_label",
        "feature_2_label",
        "feature_1_label",
    ):
        op.drop_column("event_classes", column_name, schema="catalog")

    op.execute(
        "UPDATE catalog.event_features_2 SET name = '-' WHERE name IS NULL"
    )
    op.execute(
        "UPDATE catalog.event_features_3 SET name = '-' WHERE name IS NULL"
    )
    op.alter_column(
        "event_features_3",
        "name",
        existing_type=sa.String(length=1024),
        nullable=False,
        schema="catalog",
    )
    op.alter_column(
        "event_features_2",
        "name",
        existing_type=sa.String(length=1024),
        nullable=False,
        schema="catalog",
    )

    op.drop_constraint(
        op.f("ck_event_types_code_range"),
        "event_types",
        schema="catalog",
        type_="check",
    )
    op.create_check_constraint(
        "code_range",
        "event_types",
        "code BETWEEN 1 AND 9",
        schema="catalog",
    )
