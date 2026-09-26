"""Card requirements, event-specific fields and classifier service routes.

Revision ID: 0006_card_services
Revises: 0005_classifier_import_fields
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006_card_services"
down_revision: str | None = "0005_classifier_import_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    for name in (
        "has_victims_or_deceased",
        "ambulance_refused_or_not_on_scene",
        "no_access_or_blocked",
    ):
        op.add_column(
            "incident_card_details",
            sa.Column(name, sa.Boolean(), nullable=True),
            schema="content",
        )
    # Old draft rows remain readable; new and changed rows must keep the pair together.
    op.execute(
        "ALTER TABLE content.incident_card_details ADD CONSTRAINT "
        "ck_incident_card_details_control_fields_together "
        "CHECK ((controlled_at IS NULL) = (controlled_by_name IS NULL)) NOT VALID"
    )

    op.create_table(
        "event_additional_fields",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event_class_id", UUID, sa.ForeignKey("catalog.event_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("data_type", sa.String(16), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("options", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("event_class_id", "field_key"),
        sa.CheckConstraint("data_type IN ('text', 'integer', 'number', 'boolean', 'date', 'datetime', 'select')", name="data_type_values"),
        sa.CheckConstraint("jsonb_typeof(options) = 'array'", name="options_array"),
        schema="catalog",
    )
    op.create_table(
        "exercise_additional_values",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("exercise_revision_id", UUID, sa.ForeignKey("content.exercise_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_field_id", UUID, sa.ForeignKey("catalog.event_additional_fields.id", ondelete="SET NULL"), nullable=True),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("data_type", sa.String(16), nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False),
        sa.Column("options", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint("exercise_revision_id", "field_key"),
        sa.CheckConstraint("data_type IN ('text', 'integer', 'number', 'boolean', 'date', 'datetime', 'select')", name="data_type_values"),
        sa.CheckConstraint("jsonb_typeof(options) = 'array'", name="options_array"),
        sa.CheckConstraint(
            "value IS NULL OR value = 'null'::jsonb OR "
            "(data_type = 'boolean' AND jsonb_typeof(value) = 'boolean') OR "
            "(data_type IN ('text', 'date', 'datetime', 'select') AND jsonb_typeof(value) = 'string') OR "
            "(data_type IN ('integer', 'number') AND jsonb_typeof(value) = 'number' "
            "AND (data_type = 'number' OR value::text ~ '^-?[0-9]+$'))",
            name="value_matches_type",
        ),
        schema="content",
    )
    op.execute("""
        CREATE TRIGGER trg_event_additional_fields_updated_at
        BEFORE UPDATE ON catalog.event_additional_fields
        FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at()
    """)
    op.create_index(
        "ix_exercise_additional_values_source_field_id",
        "exercise_additional_values", ["source_field_id"], schema="content"
    )
    op.create_table(
        "event_service_routes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event_class_id", UUID, sa.ForeignKey("catalog.event_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_id", UUID, sa.ForeignKey("catalog.services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_column", sa.String(3), nullable=False),
        sa.Column("condition_code", sa.String(64), nullable=False),
        sa.Column("condition_label", sa.String(512), nullable=True),
        sa.Column("response_label", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.UniqueConstraint("event_class_id", "service_id", "source_column"),
        sa.CheckConstraint("length(trim(source_column)) > 0", name="source_column_nonempty"),
        schema="catalog",
    )
    op.create_index("ix_event_service_routes_service_id", "event_service_routes", ["service_id"], schema="catalog")

    op.execute("""
        CREATE FUNCTION content.sync_revision_additional_fields() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.event_class_id IS DISTINCT FROM OLD.event_class_id THEN
                IF EXISTS (
                    SELECT 1 FROM content.exercise_additional_values
                    WHERE exercise_revision_id = NEW.id AND value IS NOT NULL
                ) THEN
                    RAISE EXCEPTION 'Create a new revision before changing a classified card with filled additional fields';
                END IF;
                DELETE FROM content.exercise_additional_values WHERE exercise_revision_id = NEW.id;
            END IF;
            IF NEW.event_class_id IS NOT NULL THEN
                INSERT INTO content.exercise_additional_values
                    (id, exercise_revision_id, source_field_id, field_key, label,
                     data_type, is_required, options, display_order)
                SELECT md5(random()::text || clock_timestamp()::text)::uuid,
                       NEW.id, f.id, f.field_key, f.label,
                       f.data_type, f.is_required, f.options, f.display_order
                FROM catalog.event_additional_fields AS f
                WHERE f.event_class_id = NEW.event_class_id
                ON CONFLICT (exercise_revision_id, field_key) DO NOTHING;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_revision_additional_fields
        AFTER INSERT OR UPDATE OF event_class_id ON content.exercise_revisions
        FOR EACH ROW EXECUTE FUNCTION content.sync_revision_additional_fields()
    """)
    op.execute("""
        CREATE FUNCTION content.seed_new_event_field() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO content.exercise_additional_values
                (id, exercise_revision_id, source_field_id, field_key, label,
                 data_type, is_required, options, display_order)
            SELECT md5(random()::text || clock_timestamp()::text)::uuid,
                   r.id, NEW.id, NEW.field_key, NEW.label,
                   NEW.data_type, NEW.is_required, NEW.options, NEW.display_order
            FROM content.exercise_revisions AS r
            WHERE r.event_class_id = NEW.event_class_id
              AND r.review_status IN ('draft', 'review')
            ON CONFLICT (exercise_revision_id, field_key) DO NOTHING;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_seed_new_event_field
        AFTER INSERT ON catalog.event_additional_fields
        FOR EACH ROW EXECUTE FUNCTION content.seed_new_event_field()
    """)

    op.execute("""
        CREATE FUNCTION catalog.assert_event_has_service(p_event_class_id uuid)
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM catalog.event_classes AS e WHERE e.id = p_event_class_id
            ) AND NOT EXISTS (
                SELECT 1 FROM catalog.event_class_services AS s
                WHERE s.event_class_id = p_event_class_id
            ) AND NOT EXISTS (
                SELECT 1 FROM catalog.event_classes AS e
                WHERE e.id = p_event_class_id AND e.main_service_id IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Event class % must have at least one service', p_event_class_id;
            END IF;
        END $$
    """)
    op.execute("""
        CREATE FUNCTION catalog.matching_service_routes(
            p_event_class_id uuid, p_flags jsonb DEFAULT '{}'::jsonb
        ) RETURNS TABLE (
            service_id uuid, service_code varchar, service_name varchar,
            condition_code varchar, response_label text, is_primary boolean
        ) LANGUAGE sql STABLE AS $$
            WITH candidates AS (
                SELECT r.service_id, s.code, s.name, r.condition_code,
                       r.response_label, r.is_primary
                FROM catalog.event_service_routes AS r
                JOIN catalog.services AS s ON s.id = r.service_id
                WHERE r.event_class_id = p_event_class_id
                  AND (
                      r.condition_code = 'always'
                      OR (r.condition_code = 'victims'
                          AND p_flags ->> 'has_victims_or_deceased' = 'true')
                      OR (r.condition_code = 'no_victims'
                          AND p_flags ->> 'has_victims_or_deceased' = 'false')
                      OR (r.condition_code = 'no_access'
                          AND p_flags ->> 'no_access_or_blocked' = 'true')
                      OR (r.condition_code = 'no_access_false'
                          AND p_flags ->> 'no_access_or_blocked' = 'false')
                      OR (r.condition_code = 'no_violation_or_victims'
                          AND p_flags ->> 'law_violation' = 'false'
                          AND p_flags ->> 'has_victims_or_deceased' = 'false')
                      OR (p_flags ->> r.condition_code = 'true')
                  )
                UNION ALL
                SELECT e.main_service_id, s.code, s.name, 'always'::varchar,
                       NULL::text, true
                FROM catalog.event_classes AS e
                JOIN catalog.services AS s ON s.id = e.main_service_id
                WHERE e.id = p_event_class_id
                  AND NOT EXISTS (
                      SELECT 1 FROM catalog.event_service_routes AS r
                      WHERE r.event_class_id = e.id AND r.service_id = e.main_service_id
                  )
                UNION ALL
                SELECT es.service_id, s.code, s.name, 'always'::varchar,
                       NULL::text, false
                FROM catalog.event_class_services AS es
                JOIN catalog.services AS s ON s.id = es.service_id
                WHERE es.event_class_id = p_event_class_id
                  AND NOT EXISTS (
                      SELECT 1 FROM catalog.event_service_routes AS r
                      WHERE r.event_class_id = es.event_class_id
                        AND r.service_id = es.service_id
                  )
            )
            SELECT DISTINCT ON (c.service_id) c.service_id, c.code, c.name,
                   c.condition_code, c.response_label, c.is_primary
            FROM candidates AS c
            ORDER BY c.service_id, c.is_primary DESC
        $$
    """)
    op.execute("""
        CREATE FUNCTION catalog.check_event_has_service() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME = 'event_classes' THEN
                PERFORM catalog.assert_event_has_service(NEW.id);
            ELSIF TG_OP = 'DELETE' THEN
                PERFORM catalog.assert_event_has_service(OLD.event_class_id);
            ELSE
                PERFORM catalog.assert_event_has_service(NEW.event_class_id);
                IF TG_OP = 'UPDATE' AND OLD.event_class_id <> NEW.event_class_id THEN
                    PERFORM catalog.assert_event_has_service(OLD.event_class_id);
                END IF;
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_event_requires_service
        AFTER INSERT OR UPDATE ON catalog.event_classes
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION catalog.check_event_has_service()
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_event_service_removal_check
        AFTER DELETE OR UPDATE OF event_class_id ON catalog.event_class_services
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
        EXECUTE FUNCTION catalog.check_event_has_service()
    """)

    op.execute("""
        CREATE FUNCTION content.assert_approved_exercise(p_exercise_id uuid)
        RETURNS void LANGUAGE plpgsql AS $$
        DECLARE card record;
        BEGIN
            SELECT e.status, r.id AS revision_id, r.review_status, r.event_class_id,
                   d.registered_by_name, d.controlled_at, d.controlled_by_name,
                   d.aon_phone, d.applicant_phone, d.applicant_full_name,
                   d.applicant_status, d.country, d.federal_subject, d.locality,
                   d.street, d.descriptive_address, d.latitude, d.longitude,
                   d.incident_description
            INTO card
            FROM content.exercises AS e
            LEFT JOIN content.exercise_revisions AS r ON r.id = e.active_revision_id
                AND r.exercise_id = e.id
            LEFT JOIN content.incident_card_details AS d ON d.exercise_revision_id = r.id
            WHERE e.id = p_exercise_id;
            IF NOT FOUND OR card.status <> 'approved' THEN RETURN; END IF;
            IF card.revision_id IS NULL OR card.review_status <> 'approved'
               OR card.event_class_id IS NULL
               OR nullif(btrim(card.registered_by_name), '') IS NULL
               OR card.controlled_at IS NULL
               OR nullif(btrim(card.controlled_by_name), '') IS NULL
               OR nullif(btrim(card.aon_phone), '') IS NULL
               OR nullif(btrim(card.applicant_phone), '') IS NULL
               OR nullif(btrim(card.applicant_full_name), '') IS NULL
               OR nullif(btrim(card.applicant_status), '') IS NULL
               OR nullif(btrim(card.country), '') IS NULL
               OR nullif(btrim(card.federal_subject), '') IS NULL
               OR nullif(btrim(card.locality), '') IS NULL
               OR card.latitude IS NULL OR card.longitude IS NULL
               OR nullif(btrim(card.incident_description), '') IS NULL
               OR (nullif(btrim(card.street), '') IS NULL
                   AND nullif(btrim(card.descriptive_address), '') IS NULL) THEN
                RAISE EXCEPTION 'Approved exercise % lacks required card details or classification', p_exercise_id;
            END IF;
            IF EXISTS (
                SELECT 1 FROM content.exercise_additional_values AS v
                WHERE v.exercise_revision_id = card.revision_id
                  AND v.is_required AND (v.value IS NULL OR v.value = 'null'::jsonb)
            ) THEN
                RAISE EXCEPTION 'Approved exercise % has unfilled required additional fields', p_exercise_id;
            END IF;
            PERFORM catalog.assert_event_has_service(card.event_class_id);
        END $$
    """)
    op.execute("""
        CREATE FUNCTION content.check_approved_exercise() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE exercise_key uuid;
        BEGIN
            IF TG_TABLE_NAME = 'exercises' THEN
                exercise_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
            ELSIF TG_TABLE_NAME = 'exercise_revisions' THEN
                exercise_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.exercise_id ELSE NEW.exercise_id END;
            ELSIF TG_TABLE_NAME = 'incident_card_details' THEN
                SELECT exercise_id INTO exercise_key FROM content.exercise_revisions
                WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.exercise_revision_id
                                ELSE NEW.exercise_revision_id END;
            ELSE
                SELECT r.exercise_id INTO exercise_key FROM content.exercise_revisions AS r
                WHERE r.id = CASE WHEN TG_OP = 'DELETE' THEN OLD.exercise_revision_id
                                  ELSE NEW.exercise_revision_id END;
            END IF;
            IF exercise_key IS NOT NULL THEN
                PERFORM content.assert_approved_exercise(exercise_key);
            END IF;
            RETURN NULL;
        END $$
    """)
    for schema, table in (
        ("content", "exercises"),
        ("content", "exercise_revisions"),
        ("content", "incident_card_details"),
        ("content", "exercise_additional_values"),
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_approved_check "
            f"AFTER INSERT OR UPDATE OR DELETE ON {schema}.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION content.check_approved_exercise()"
        )


def downgrade() -> None:
    for table in (
        "exercise_additional_values", "incident_card_details",
        "exercise_revisions", "exercises",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_approved_check ON content.{table}")
    op.execute("DROP FUNCTION content.check_approved_exercise()")
    op.execute("DROP FUNCTION content.assert_approved_exercise(uuid)")
    op.execute("DROP TRIGGER trg_event_service_removal_check ON catalog.event_class_services")
    op.execute("DROP TRIGGER trg_event_requires_service ON catalog.event_classes")
    op.execute("DROP FUNCTION catalog.matching_service_routes(uuid, jsonb)")
    op.execute("DROP FUNCTION catalog.check_event_has_service()")
    op.execute("DROP FUNCTION catalog.assert_event_has_service(uuid)")
    op.execute("DROP TRIGGER trg_seed_new_event_field ON catalog.event_additional_fields")
    op.execute("DROP FUNCTION content.seed_new_event_field()")
    op.execute("DROP TRIGGER trg_revision_additional_fields ON content.exercise_revisions")
    op.execute("DROP FUNCTION content.sync_revision_additional_fields()")
    op.execute("DROP TRIGGER trg_event_additional_fields_updated_at ON catalog.event_additional_fields")
    op.drop_table("event_service_routes", schema="catalog")
    op.drop_table("exercise_additional_values", schema="content")
    op.drop_table("event_additional_fields", schema="catalog")
    op.execute("ALTER TABLE content.incident_card_details DROP CONSTRAINT ck_incident_card_details_control_fields_together")
    for name in (
        "no_access_or_blocked",
        "ambulance_refused_or_not_on_scene",
        "has_victims_or_deceased",
    ):
        op.drop_column("incident_card_details", name, schema="content")
