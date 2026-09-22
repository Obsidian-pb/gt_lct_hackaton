"""Rename event groups to the first classifier feature.

Revision ID: 0004_rename_event_feature_1
Revises: 0003_incident_card_details
"""
from typing import Sequence

from alembic import op


revision: str = "0004_rename_event_feature_1"
down_revision: str | None = "0003_incident_card_details"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_event_number_function(*, feature_1: bool) -> None:
    if feature_1:
        first_id = "event_feature_1_id"
        first_table = "event_features_1"
        first_code = "feature_1_code"
    else:
        first_id = "event_group_id"
        first_table = "event_groups"
        first_code = "group_code"

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION catalog.assign_event_number()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            type_code integer;
            {first_code} integer;
            feature_2_code integer;
            feature_3_code integer;
        BEGIN
            IF TG_OP = 'INSERT'
               AND NEW.event_type_id IS NULL
               AND NEW.{first_id} IS NULL
               AND NEW.event_feature_2_id IS NULL
               AND NEW.event_feature_3_id IS NULL THEN
                RAISE EXCEPTION 'A new event class must contain classifier components';
            END IF;

            IF TG_OP = 'UPDATE'
               AND OLD.event_number IS NOT NULL
               AND (OLD.event_type_id, OLD.{first_id}, OLD.event_feature_2_id, OLD.event_feature_3_id)
                   IS DISTINCT FROM
                   (NEW.event_type_id, NEW.{first_id}, NEW.event_feature_2_id, NEW.event_feature_3_id) THEN
                RAISE EXCEPTION 'An event number and its classifier components are immutable';
            END IF;

            IF NEW.event_type_id IS NULL
               AND NEW.{first_id} IS NULL
               AND NEW.event_feature_2_id IS NULL
               AND NEW.event_feature_3_id IS NULL THEN
                NEW.event_number := NULL;
                RETURN NEW;
            END IF;

            IF NEW.event_type_id IS NULL
               OR NEW.{first_id} IS NULL
               OR NEW.event_feature_2_id IS NULL
               OR NEW.event_feature_3_id IS NULL THEN
                RAISE EXCEPTION 'All event classifier components must be specified';
            END IF;

            SELECT event_types.code, {first_table}.code,
                   event_features_2.code, event_features_3.code
              INTO type_code, {first_code}, feature_2_code, feature_3_code
              FROM catalog.event_types
              JOIN catalog.{first_table}
                ON {first_table}.event_type_id = event_types.id
              JOIN catalog.event_features_2
                ON event_features_2.{first_id} = {first_table}.id
              JOIN catalog.event_features_3
                ON event_features_3.event_feature_2_id = event_features_2.id
             WHERE event_types.id = NEW.event_type_id
               AND {first_table}.id = NEW.{first_id}
               AND event_features_2.id = NEW.event_feature_2_id
               AND event_features_3.id = NEW.event_feature_3_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Event classifier components do not form one hierarchy';
            END IF;

            NEW.event_number :=
                type_code * 1000000
                + {first_code} * 10000
                + feature_2_code * 100
                + feature_3_code;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_event_classes_assign_event_number "
        "ON catalog.event_classes"
    )
    op.execute(
        "ALTER TRIGGER trg_event_groups_immutable_code ON catalog.event_groups "
        "RENAME TO trg_event_features_1_immutable_code"
    )

    op.rename_table("event_groups", "event_features_1", schema="catalog")
    op.alter_column(
        "event_features_2",
        "event_group_id",
        new_column_name="event_feature_1_id",
        schema="catalog",
    )
    op.alter_column(
        "event_classes",
        "event_group_id",
        new_column_name="event_feature_1_id",
        schema="catalog",
    )

    constraint_renames = (
        (
            "catalog.event_features_1",
            "pk_event_groups",
            "pk_event_features_1",
        ),
        (
            "catalog.event_features_1",
            "uq_event_groups_event_type_id",
            "uq_event_features_1_event_type_id",
        ),
        (
            "catalog.event_features_1",
            "ck_event_groups_code_range",
            "ck_event_features_1_code_range",
        ),
        (
            "catalog.event_features_1",
            "fk_event_groups_event_type_id_event_types",
            "fk_event_features_1_event_type_id_event_types",
        ),
        (
            "catalog.event_features_2",
            "uq_event_features_2_event_group_id",
            "uq_event_features_2_event_feature_1_id",
        ),
        (
            "catalog.event_features_2",
            "fk_event_features_2_event_group_id_event_groups",
            "fk_event_features_2_event_feature_1_id_event_features_1",
        ),
        (
            "catalog.event_classes",
            "fk_event_classes_event_group_id_event_groups",
            "fk_event_classes_event_feature_1_id_event_features_1",
        ),
    )
    for table_name, old_name, new_name in constraint_renames:
        op.execute(
            f"ALTER TABLE {table_name} RENAME CONSTRAINT {old_name} TO {new_name}"
        )

    _replace_event_number_function(feature_1=True)
    op.execute(
        """
        CREATE TRIGGER trg_event_classes_assign_event_number
        BEFORE INSERT OR UPDATE OF event_number, event_type_id, event_feature_1_id,
            event_feature_2_id, event_feature_3_id
        ON catalog.event_classes
        FOR EACH ROW EXECUTE FUNCTION catalog.assign_event_number()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_event_classes_assign_event_number "
        "ON catalog.event_classes"
    )

    constraint_renames = (
        (
            "catalog.event_classes",
            "fk_event_classes_event_feature_1_id_event_features_1",
            "fk_event_classes_event_group_id_event_groups",
        ),
        (
            "catalog.event_features_2",
            "fk_event_features_2_event_feature_1_id_event_features_1",
            "fk_event_features_2_event_group_id_event_groups",
        ),
        (
            "catalog.event_features_2",
            "uq_event_features_2_event_feature_1_id",
            "uq_event_features_2_event_group_id",
        ),
        (
            "catalog.event_features_1",
            "fk_event_features_1_event_type_id_event_types",
            "fk_event_groups_event_type_id_event_types",
        ),
        (
            "catalog.event_features_1",
            "ck_event_features_1_code_range",
            "ck_event_groups_code_range",
        ),
        (
            "catalog.event_features_1",
            "uq_event_features_1_event_type_id",
            "uq_event_groups_event_type_id",
        ),
        (
            "catalog.event_features_1",
            "pk_event_features_1",
            "pk_event_groups",
        ),
    )
    for table_name, old_name, new_name in constraint_renames:
        op.execute(
            f"ALTER TABLE {table_name} RENAME CONSTRAINT {old_name} TO {new_name}"
        )

    op.alter_column(
        "event_classes",
        "event_feature_1_id",
        new_column_name="event_group_id",
        schema="catalog",
    )
    op.alter_column(
        "event_features_2",
        "event_feature_1_id",
        new_column_name="event_group_id",
        schema="catalog",
    )
    op.execute(
        "ALTER TRIGGER trg_event_features_1_immutable_code "
        "ON catalog.event_features_1 RENAME TO trg_event_groups_immutable_code"
    )
    op.rename_table("event_features_1", "event_groups", schema="catalog")

    _replace_event_number_function(feature_1=False)
    op.execute(
        """
        CREATE TRIGGER trg_event_classes_assign_event_number
        BEFORE INSERT OR UPDATE OF event_number, event_type_id, event_group_id,
            event_feature_2_id, event_feature_3_id
        ON catalog.event_classes
        FOR EACH ROW EXECUTE FUNCTION catalog.assign_event_number()
        """
    )
