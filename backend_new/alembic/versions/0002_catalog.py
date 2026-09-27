"""catalog: классификатор происшествий, службы, версии классификатора

Revision ID: 0002_catalog
Revises: 0001_auth
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_catalog"
down_revision: Union[str, None] = "0001_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS catalog")

    op.create_table(
        "classifier_versions",
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
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_name", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "version_number > 0", name=op.f("ck_classifier_versions_version_number_positive")
        ),
        sa.ForeignKeyConstraint(
            ["published_by"],
            ["auth.users.id"],
            name=op.f("fk_classifier_versions_published_by_users"),
            ondelete="SET NULL",
        ),
        sa.Index(
            "uq_classifier_versions_active",
            "is_active",
            unique=True,
            postgresql_where=sa.text("is_active"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classifier_versions")),
        sa.UniqueConstraint(
            "version_number", name=op.f("uq_classifier_versions_version_number")
        ),
        schema="catalog",
    )

    op.create_table(
        "event_types",
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
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint("code BETWEEN 1 AND 9", name=op.f("ck_event_types_code_range")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_types")),
        sa.UniqueConstraint("code", name=op.f("uq_event_types_code")),
        schema="catalog",
    )

    op.create_table(
        "event_features_1",
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
        sa.Column("event_type_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("statistics_name", sa.String(length=512), nullable=False),
        sa.Column("operator_label", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "code BETWEEN 0 AND 99", name=op.f("ck_event_features_1_code_range")
        ),
        sa.ForeignKeyConstraint(
            ["event_type_id"],
            ["catalog.event_types.id"],
            name=op.f("fk_event_features_1_event_type_id_event_types"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_features_1")),
        sa.UniqueConstraint(
            "event_type_id", "code", name=op.f("uq_event_features_1_event_type_id")
        ),
        schema="catalog",
    )

    op.create_table(
        "event_features_2",
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
        sa.Column("event_feature_1_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "code BETWEEN 0 AND 99", name=op.f("ck_event_features_2_code_range")
        ),
        sa.ForeignKeyConstraint(
            ["event_feature_1_id"],
            ["catalog.event_features_1.id"],
            name=op.f("fk_event_features_2_event_feature_1_id_event_features_1"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_features_2")),
        sa.UniqueConstraint(
            "event_feature_1_id", "code", name=op.f("uq_event_features_2_event_feature_1_id")
        ),
        schema="catalog",
    )

    op.create_table(
        "event_features_3",
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
        sa.Column("event_feature_2_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "code BETWEEN 0 AND 99", name=op.f("ck_event_features_3_code_range")
        ),
        sa.ForeignKeyConstraint(
            ["event_feature_2_id"],
            ["catalog.event_features_2.id"],
            name=op.f("fk_event_features_3_event_feature_2_id_event_features_2"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_features_3")),
        sa.UniqueConstraint(
            "event_feature_2_id", "code", name=op.f("uq_event_features_3_event_feature_2_id")
        ),
        schema="catalog",
    )

    op.create_table(
        "services",
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
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_services")),
        sa.UniqueConstraint("code", name=op.f("uq_services_code")),
        schema="catalog",
    )

    op.create_table(
        "event_classes",
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
        sa.Column("event_number", sa.BigInteger(), nullable=False),
        sa.Column("event_type_id", sa.Uuid(), nullable=False),
        sa.Column("event_feature_1_id", sa.Uuid(), nullable=False),
        sa.Column("event_feature_2_id", sa.Uuid(), nullable=False),
        sa.Column("event_feature_3_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ekp35_type", sa.String(length=512), nullable=True),
        sa.Column("scenario_code", sa.String(length=64), nullable=True),
        sa.Column("main_service_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_feature_1_id"],
            ["catalog.event_features_1.id"],
            name=op.f("fk_event_classes_event_feature_1_id_event_features_1"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_feature_2_id"],
            ["catalog.event_features_2.id"],
            name=op.f("fk_event_classes_event_feature_2_id_event_features_2"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_feature_3_id"],
            ["catalog.event_features_3.id"],
            name=op.f("fk_event_classes_event_feature_3_id_event_features_3"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_type_id"],
            ["catalog.event_types.id"],
            name=op.f("fk_event_classes_event_type_id_event_types"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["main_service_id"],
            ["catalog.services.id"],
            name=op.f("fk_event_classes_main_service_id_services"),
            ondelete="SET NULL",
        ),
        sa.Index("ix_event_classes_event_number", "event_number", unique=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_classes")),
        sa.UniqueConstraint(
            "event_type_id",
            "event_feature_1_id",
            "event_feature_2_id",
            "event_feature_3_id",
            name=op.f("uq_event_classes_components"),
        ),
        schema="catalog",
    )

    op.create_table(
        "event_class_extra_fields",
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
        sa.Column("event_class_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("field_type", sa.String(length=16), nullable=False),
        sa.Column(
            "required", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.CheckConstraint(
            "field_type IN ('text', 'number', 'boolean', 'select', 'date')",
            name=op.f("ck_event_class_extra_fields_field_type_values"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array'",
            name=op.f("ck_event_class_extra_fields_options_array"),
        ),
        sa.ForeignKeyConstraint(
            ["event_class_id"],
            ["catalog.event_classes.id"],
            name=op.f("fk_event_class_extra_fields_event_class_id_event_classes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_class_extra_fields")),
        sa.UniqueConstraint(
            "event_class_id",
            "code",
            name=op.f("uq_event_class_extra_fields_event_class_id"),
        ),
        schema="catalog",
    )

    op.create_table(
        "classifier_version_events",
        sa.Column("classifier_version_id", sa.Uuid(), nullable=False),
        sa.Column("event_class_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["classifier_version_id"],
            ["catalog.classifier_versions.id"],
            name=op.f(
                "fk_classifier_version_events_classifier_version_id_classifier_versions"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_class_id"],
            ["catalog.event_classes.id"],
            name=op.f("fk_classifier_version_events_event_class_id_event_classes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "classifier_version_id",
            "event_class_id",
            name=op.f("pk_classifier_version_events"),
        ),
        schema="catalog",
    )

    op.create_table(
        "event_class_services",
        sa.Column("event_class_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_class_id"],
            ["catalog.event_classes.id"],
            name=op.f("fk_event_class_services_event_class_id_event_classes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["catalog.services.id"],
            name=op.f("fk_event_class_services_service_id_services"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "event_class_id", "service_id", name=op.f("pk_event_class_services")
        ),
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_table("event_class_services", schema="catalog")
    op.drop_table("classifier_version_events", schema="catalog")
    op.drop_table("event_class_extra_fields", schema="catalog")
    op.drop_table("event_classes", schema="catalog")
    op.drop_table("services", schema="catalog")
    op.drop_table("event_features_3", schema="catalog")
    op.drop_table("event_features_2", schema="catalog")
    op.drop_table("event_features_1", schema="catalog")
    op.drop_table("event_types", schema="catalog")
    op.drop_table("classifier_versions", schema="catalog")
    op.execute("DROP SCHEMA IF EXISTS catalog")