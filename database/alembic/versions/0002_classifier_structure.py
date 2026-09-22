"""Add the versioned incident classifier and card classification structure.

Revision ID: 0002_classifier_structure
Revises: 0001_initial_schema
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_classifier_structure"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "classifier_versions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_name", sa.String(512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "published_by",
            UUID,
            sa.ForeignKey("auth.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("version_number", name="uq_classifier_versions_version_number"),
        sa.CheckConstraint("version_number > 0", name="version_number_positive"),
        schema="catalog",
    )
    op.create_index(
        "uq_classifier_versions_active",
        "classifier_versions",
        ["is_active"],
        unique=True,
        schema="catalog",
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "event_types",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("code", name="uq_event_types_code"),
        sa.CheckConstraint("code BETWEEN 1 AND 9", name="code_range"),
        schema="catalog",
    )
    op.create_table(
        "event_groups",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "event_type_id",
            UUID,
            sa.ForeignKey("catalog.event_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("statistics_name", sa.String(512), nullable=False),
        sa.Column("operator_label", sa.String(512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("event_type_id", "code", name="uq_event_groups_event_type_id"),
        sa.CheckConstraint("code BETWEEN 0 AND 99", name="code_range"),
        schema="catalog",
    )
    op.create_table(
        "event_features_2",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "event_group_id",
            UUID,
            sa.ForeignKey("catalog.event_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("event_group_id", "code", name="uq_event_features_2_event_group_id"),
        sa.CheckConstraint("code BETWEEN 0 AND 99", name="code_range"),
        schema="catalog",
    )
    op.create_table(
        "event_features_3",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "event_feature_2_id",
            UUID,
            sa.ForeignKey("catalog.event_features_2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(1024), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "event_feature_2_id", "code", name="uq_event_features_3_event_feature_2_id"
        ),
        sa.CheckConstraint("code BETWEEN 0 AND 99", name="code_range"),
        schema="catalog",
    )

    op.alter_column(
        "event_classes", "code", new_column_name="legacy_code", schema="catalog"
    )
    op.drop_constraint("uq_event_classes_code", "event_classes", schema="catalog")
    op.alter_column(
        "event_classes", "legacy_code", existing_type=sa.String(64), nullable=True, schema="catalog"
    )
    op.create_unique_constraint(
        "uq_event_classes_legacy_code", "event_classes", ["legacy_code"], schema="catalog"
    )
    op.add_column("event_classes", sa.Column("event_number", sa.BigInteger()), schema="catalog")
    op.add_column("event_classes", sa.Column("event_type_id", UUID), schema="catalog")
    op.add_column("event_classes", sa.Column("event_group_id", UUID), schema="catalog")
    op.add_column("event_classes", sa.Column("event_feature_2_id", UUID), schema="catalog")
    op.add_column("event_classes", sa.Column("event_feature_3_id", UUID), schema="catalog")
    op.add_column("event_classes", sa.Column("ekp35_type", sa.String(512)), schema="catalog")
    op.add_column("event_classes", sa.Column("scenario_code", sa.String(64)), schema="catalog")
    op.add_column("event_classes", sa.Column("main_service_id", UUID), schema="catalog")
    op.create_foreign_key(
        "fk_event_classes_event_type_id_event_types",
        "event_classes",
        "event_types",
        ["event_type_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_event_classes_event_group_id_event_groups",
        "event_classes",
        "event_groups",
        ["event_group_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_event_classes_event_feature_2_id_event_features_2",
        "event_classes",
        "event_features_2",
        ["event_feature_2_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_event_classes_event_feature_3_id_event_features_3",
        "event_classes",
        "event_features_3",
        ["event_feature_3_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_event_classes_main_service_id_services",
        "event_classes",
        "services",
        ["main_service_id"],
        ["id"],
        source_schema="catalog",
        referent_schema="catalog",
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_event_classes_components",
        "event_classes",
        ["event_type_id", "event_group_id", "event_feature_2_id", "event_feature_3_id"],
        schema="catalog",
    )
    op.create_check_constraint(
        "classification_complete",
        "event_classes",
        "legacy_code IS NOT NULL OR (event_number IS NOT NULL AND event_type_id IS NOT NULL "
        "AND event_group_id IS NOT NULL AND event_feature_2_id IS NOT NULL "
        "AND event_feature_3_id IS NOT NULL)",
        schema="catalog",
    )
    op.create_index(
        "ix_event_classes_event_number",
        "event_classes",
        ["event_number"],
        unique=True,
        schema="catalog",
    )

    op.create_table(
        "classifier_version_events",
        sa.Column(
            "classifier_version_id",
            UUID,
            sa.ForeignKey("catalog.classifier_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "event_class_id",
            UUID,
            sa.ForeignKey("catalog.event_classes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        schema="catalog",
    )
    op.create_table(
        "event_class_services",
        sa.Column(
            "event_class_id",
            UUID,
            sa.ForeignKey("catalog.event_classes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "service_id",
            UUID,
            sa.ForeignKey("catalog.services.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema="catalog",
    )

    op.execute(
        """
        CREATE FUNCTION catalog.assign_event_number()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            type_code integer;
            group_code integer;
            feature_2_code integer;
            feature_3_code integer;
        BEGIN
            IF TG_OP = 'INSERT'
               AND NEW.event_type_id IS NULL
               AND NEW.event_group_id IS NULL
               AND NEW.event_feature_2_id IS NULL
               AND NEW.event_feature_3_id IS NULL THEN
                RAISE EXCEPTION 'A new event class must contain classifier components';
            END IF;

            IF TG_OP = 'UPDATE'
               AND OLD.event_number IS NOT NULL
               AND (OLD.event_type_id, OLD.event_group_id, OLD.event_feature_2_id, OLD.event_feature_3_id)
                   IS DISTINCT FROM
                   (NEW.event_type_id, NEW.event_group_id, NEW.event_feature_2_id, NEW.event_feature_3_id) THEN
                RAISE EXCEPTION 'An event number and its classifier components are immutable';
            END IF;

            IF NEW.event_type_id IS NULL
               AND NEW.event_group_id IS NULL
               AND NEW.event_feature_2_id IS NULL
               AND NEW.event_feature_3_id IS NULL THEN
                NEW.event_number := NULL;
                RETURN NEW;
            END IF;

            IF NEW.event_type_id IS NULL
               OR NEW.event_group_id IS NULL
               OR NEW.event_feature_2_id IS NULL
               OR NEW.event_feature_3_id IS NULL THEN
                RAISE EXCEPTION 'All event classifier components must be specified';
            END IF;

            SELECT event_types.code, event_groups.code,
                   event_features_2.code, event_features_3.code
              INTO type_code, group_code, feature_2_code, feature_3_code
              FROM catalog.event_types
              JOIN catalog.event_groups
                ON event_groups.event_type_id = event_types.id
              JOIN catalog.event_features_2
                ON event_features_2.event_group_id = event_groups.id
              JOIN catalog.event_features_3
                ON event_features_3.event_feature_2_id = event_features_2.id
             WHERE event_types.id = NEW.event_type_id
               AND event_groups.id = NEW.event_group_id
               AND event_features_2.id = NEW.event_feature_2_id
               AND event_features_3.id = NEW.event_feature_3_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Event classifier components do not form one hierarchy';
            END IF;

            NEW.event_number :=
                type_code * 1000000
                + group_code * 10000
                + feature_2_code * 100
                + feature_3_code;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_event_classes_assign_event_number
        BEFORE INSERT OR UPDATE OF event_number, event_type_id, event_group_id,
            event_feature_2_id, event_feature_3_id
        ON catalog.event_classes
        FOR EACH ROW EXECUTE FUNCTION catalog.assign_event_number()
        """
    )
    op.execute(
        """
        CREATE FUNCTION catalog.prevent_classifier_code_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.code IS DISTINCT FROM OLD.code THEN
                RAISE EXCEPTION 'Classifier codes are immutable; create a new entry instead';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in (
        "event_types",
        "event_groups",
        "event_features_2",
        "event_features_3",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable_code
            BEFORE UPDATE OF code ON catalog.{table_name}
            FOR EACH ROW EXECUTE FUNCTION catalog.prevent_classifier_code_change()
            """
        )

    op.drop_constraint(
        "fk_event_templates_event_class_id_event_classes",
        "event_templates",
        schema="content",
        type_="foreignkey",
    )
    op.alter_column(
        "event_templates", "event_class_id", existing_type=UUID, nullable=True, schema="content"
    )
    op.create_foreign_key(
        "fk_event_templates_event_class_id_event_classes",
        "event_templates",
        "event_classes",
        ["event_class_id"],
        ["id"],
        source_schema="content",
        referent_schema="catalog",
        ondelete="SET NULL",
    )
    op.add_column("event_templates", sa.Column("event_type_id", UUID), schema="content")
    op.create_foreign_key(
        "fk_event_templates_event_type_id_event_types",
        "event_templates",
        "event_types",
        ["event_type_id"],
        ["id"],
        source_schema="content",
        referent_schema="catalog",
        ondelete="SET NULL",
    )

    op.add_column("exercise_revisions", sa.Column("event_class_id", UUID), schema="content")
    op.add_column(
        "exercise_revisions",
        sa.Column(
            "classification_status",
            sa.String(16),
            server_default="proposed",
            nullable=False,
        ),
        schema="content",
    )
    op.add_column(
        "exercise_revisions",
        sa.Column(
            "classification_proposal",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="content",
    )
    op.add_column(
        "exercise_revisions",
        sa.Column(
            "additional_attributes",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="content",
    )
    op.add_column("exercise_revisions", sa.Column("scenario_override", sa.String(64)), schema="content")
    op.add_column("exercise_revisions", sa.Column("main_service_override_id", UUID), schema="content")
    op.add_column(
        "exercise_revisions",
        sa.Column(
            "service_overrides",
            JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="content",
    )
    op.add_column("exercise_revisions", sa.Column("override_comment", sa.Text()), schema="content")
    op.create_foreign_key(
        "fk_exercise_revisions_event_class_id_event_classes",
        "exercise_revisions",
        "event_classes",
        ["event_class_id"],
        ["id"],
        source_schema="content",
        referent_schema="catalog",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_exercise_revisions_main_service_override_id_services",
        "exercise_revisions",
        "services",
        ["main_service_override_id"],
        ["id"],
        source_schema="content",
        referent_schema="catalog",
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "classification_status_values",
        "exercise_revisions",
        "classification_status IN ('proposed','matched','needs_review','confirmed')",
        schema="content",
    )
    op.create_check_constraint(
        "classification_proposal_object",
        "exercise_revisions",
        "jsonb_typeof(classification_proposal) = 'object'",
        schema="content",
    )
    op.create_check_constraint(
        "additional_attributes_object",
        "exercise_revisions",
        "jsonb_typeof(additional_attributes) = 'object'",
        schema="content",
    )
    op.create_check_constraint(
        "service_overrides_array",
        "exercise_revisions",
        "jsonb_typeof(service_overrides) = 'array'",
        schema="content",
    )
    op.create_index(
        "ix_exercise_revisions_classification",
        "exercise_revisions",
        ["classification_status", "event_class_id"],
        schema="content",
    )

    op.add_column("sessions", sa.Column("classifier_version_id", UUID), schema="training")
    op.create_foreign_key(
        "fk_sessions_classifier_version_id_classifier_versions",
        "sessions",
        "classifier_versions",
        ["classifier_version_id"],
        ["id"],
        source_schema="training",
        referent_schema="catalog",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sessions_classifier_version_id_classifier_versions",
        "sessions",
        schema="training",
        type_="foreignkey",
    )
    op.drop_column("sessions", "classifier_version_id", schema="training")

    op.drop_index("ix_exercise_revisions_classification", table_name="exercise_revisions", schema="content")
    for constraint_name in (
        "service_overrides_array",
        "additional_attributes_object",
        "classification_proposal_object",
        "classification_status_values",
    ):
        op.drop_constraint(constraint_name, "exercise_revisions", schema="content", type_="check")
    op.drop_constraint(
        "fk_exercise_revisions_main_service_override_id_services",
        "exercise_revisions",
        schema="content",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_exercise_revisions_event_class_id_event_classes",
        "exercise_revisions",
        schema="content",
        type_="foreignkey",
    )
    for column_name in (
        "override_comment",
        "service_overrides",
        "main_service_override_id",
        "scenario_override",
        "additional_attributes",
        "classification_proposal",
        "classification_status",
        "event_class_id",
    ):
        op.drop_column("exercise_revisions", column_name, schema="content")

    op.drop_constraint(
        "fk_event_templates_event_type_id_event_types",
        "event_templates",
        schema="content",
        type_="foreignkey",
    )
    op.drop_column("event_templates", "event_type_id", schema="content")
    op.drop_constraint(
        "fk_event_templates_event_class_id_event_classes",
        "event_templates",
        schema="content",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_event_templates_event_class_id_event_classes",
        "event_templates",
        "event_classes",
        ["event_class_id"],
        ["id"],
        source_schema="content",
        referent_schema="catalog",
        ondelete="CASCADE",
    )
    op.alter_column(
        "event_templates", "event_class_id", existing_type=UUID, nullable=False, schema="content"
    )

    for table_name in (
        "event_features_3",
        "event_features_2",
        "event_groups",
        "event_types",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable_code ON catalog.{table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS catalog.prevent_classifier_code_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_event_classes_assign_event_number ON catalog.event_classes")
    op.execute("DROP FUNCTION IF EXISTS catalog.assign_event_number()")
    op.drop_table("event_class_services", schema="catalog")
    op.drop_table("classifier_version_events", schema="catalog")
    op.drop_index("ix_event_classes_event_number", table_name="event_classes", schema="catalog")
    op.drop_constraint("classification_complete", "event_classes", schema="catalog", type_="check")
    op.drop_constraint("uq_event_classes_components", "event_classes", schema="catalog", type_="unique")
    for constraint_name in (
        "fk_event_classes_main_service_id_services",
        "fk_event_classes_event_feature_3_id_event_features_3",
        "fk_event_classes_event_feature_2_id_event_features_2",
        "fk_event_classes_event_group_id_event_groups",
        "fk_event_classes_event_type_id_event_types",
    ):
        op.drop_constraint(constraint_name, "event_classes", schema="catalog", type_="foreignkey")
    for column_name in (
        "main_service_id",
        "scenario_code",
        "ekp35_type",
        "event_feature_3_id",
        "event_feature_2_id",
        "event_group_id",
        "event_type_id",
        "event_number",
    ):
        op.drop_column("event_classes", column_name, schema="catalog")
    op.drop_constraint("uq_event_classes_legacy_code", "event_classes", schema="catalog", type_="unique")
    op.alter_column(
        "event_classes", "legacy_code", existing_type=sa.String(64), nullable=False, schema="catalog"
    )
    op.alter_column(
        "event_classes", "legacy_code", new_column_name="code", schema="catalog"
    )
    op.create_unique_constraint("uq_event_classes_code", "event_classes", ["code"], schema="catalog")

    op.drop_table("event_features_3", schema="catalog")
    op.drop_table("event_features_2", schema="catalog")
    op.drop_table("event_groups", schema="catalog")
    op.drop_table("event_types", schema="catalog")
    op.drop_index("uq_classifier_versions_active", table_name="classifier_versions", schema="catalog")
    op.drop_table("classifier_versions", schema="catalog")
