"""Service-scoped assignments and permanent training-result snapshots.

Revision ID: 0007_assignments_history
Revises: 0006_card_services
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0007_assignments_history"
down_revision: str | None = "0006_card_services"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "user_services",
        sa.Column("user_id", UUID, sa.ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service_id", UUID, sa.ForeignKey("catalog.services.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("assigned_by", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        schema="auth",
    )
    op.create_index("ix_user_services_service_id", "user_services", ["service_id"], schema="auth")

    op.create_table(
        "assignments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("teacher_id", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL")),
        sa.Column("trainee_id", UUID, sa.ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_card_count", sa.Integer(), nullable=False),
        sa.Column("normative_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("requested_card_count > 0", name="card_count_positive"),
        sa.CheckConstraint("normative_seconds > 0", name="normative_seconds_positive"),
        sa.CheckConstraint("status IN ('draft', 'active', 'completed', 'cancelled')", name="status_values"),
        schema="training",
    )
    op.create_index("ix_assignments_trainee_status", "assignments", ["trainee_id", "status"], schema="training")
    op.create_table(
        "assignment_services",
        sa.Column("assignment_id", UUID, sa.ForeignKey("training.assignments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service_id", UUID, sa.ForeignKey("catalog.services.id", ondelete="CASCADE"), primary_key=True),
        schema="training",
    )
    op.create_index("ix_assignment_services_service_id", "assignment_services", ["service_id"], schema="training")
    op.create_table(
        "assignment_exercises",
        sa.Column("assignment_id", UUID, sa.ForeignKey("training.assignments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("exercise_id", UUID, sa.ForeignKey("content.exercises.id", ondelete="CASCADE"), primary_key=True),
        schema="training",
    )
    op.create_index("ix_assignment_exercises_exercise_id", "assignment_exercises", ["exercise_id"], schema="training")
    op.execute("""
        CREATE TRIGGER trg_assignments_updated_at
        BEFORE UPDATE ON training.assignments
        FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at()
    """)

    op.add_column("sessions", sa.Column("trainee_id_snapshot", UUID), schema="training")
    op.add_column("sessions", sa.Column("teacher_id_snapshot", UUID), schema="training")
    op.add_column("sessions", sa.Column("assignment_id", UUID), schema="training")
    op.add_column("sessions", sa.Column("assignment_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")), schema="training")
    op.add_column("sessions", sa.Column("normative_seconds", sa.Integer(), nullable=False, server_default="30"), schema="training")
    op.create_check_constraint("ck_sessions_normative_seconds_positive", "sessions", "normative_seconds > 0", schema="training")
    op.create_check_constraint("ck_sessions_assignment_snapshot_object", "sessions", "jsonb_typeof(assignment_snapshot) = 'object'", schema="training")
    op.execute("UPDATE training.sessions SET trainee_id_snapshot = trainee_id, teacher_id_snapshot = teacher_id")
    op.alter_column("sessions", "trainee_id_snapshot", nullable=False, schema="training")
    op.drop_constraint("fk_sessions_trainee_id_users", "sessions", schema="training", type_="foreignkey")
    op.alter_column("sessions", "trainee_id", existing_type=UUID, nullable=True, schema="training")
    op.create_foreign_key("fk_sessions_trainee_id_users", "sessions", "users", ["trainee_id"], ["id"], source_schema="training", referent_schema="auth", ondelete="SET NULL")
    op.create_foreign_key("fk_sessions_assignment_id_assignments", "sessions", "assignments", ["assignment_id"], ["id"], source_schema="training", referent_schema="training", ondelete="SET NULL")

    op.execute("""
        CREATE FUNCTION training.snapshot_assignment(p_assignment_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE AS $$
            SELECT jsonb_build_object(
                'assignment', to_jsonb(a),
                'services', COALESCE((
                    SELECT jsonb_agg(to_jsonb(svc) ORDER BY svc.code)
                    FROM training.assignment_services AS s
                    JOIN catalog.services AS svc ON svc.id = s.service_id
                    WHERE s.assignment_id = a.id
                ), '[]'::jsonb),
                'exercise_ids', COALESCE((
                    SELECT jsonb_agg(e.exercise_id ORDER BY e.exercise_id)
                    FROM training.assignment_exercises AS e WHERE e.assignment_id = a.id
                ), '[]'::jsonb)
            ) FROM training.assignments AS a WHERE a.id = p_assignment_id
        $$
    """)
    op.execute("""
        CREATE FUNCTION training.capture_session_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.trainee_id IS NULL THEN
                    RAISE EXCEPTION 'New training session requires a trainee';
                END IF;
                NEW.trainee_id_snapshot := NEW.trainee_id;
                NEW.teacher_id_snapshot := NEW.teacher_id;
                IF NEW.assignment_id IS NOT NULL THEN
                    NEW.assignment_snapshot := training.snapshot_assignment(NEW.assignment_id);
                    IF NEW.assignment_snapshot IS NULL THEN
                        RAISE EXCEPTION 'Assignment % does not exist', NEW.assignment_id;
                    END IF;
                END IF;
            ELSE
                -- SET NULL from deleting the account/assignment must not erase history.
                IF NEW.trainee_id IS NOT NULL AND NEW.trainee_id IS DISTINCT FROM OLD.trainee_id THEN
                    NEW.trainee_id_snapshot := NEW.trainee_id;
                END IF;
                IF NEW.teacher_id IS NOT NULL AND NEW.teacher_id IS DISTINCT FROM OLD.teacher_id THEN
                    NEW.teacher_id_snapshot := NEW.teacher_id;
                END IF;
                IF NEW.assignment_id IS NOT NULL AND NEW.assignment_id IS DISTINCT FROM OLD.assignment_id THEN
                    NEW.assignment_snapshot := training.snapshot_assignment(NEW.assignment_id);
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_sessions_capture_snapshot
        BEFORE INSERT OR UPDATE OF trainee_id, teacher_id, assignment_id ON training.sessions
        FOR EACH ROW EXECUTE FUNCTION training.capture_session_snapshot()
    """)

    op.add_column("session_cards", sa.Column("exercise_revision_id_snapshot", UUID), schema="training")
    op.add_column("session_cards", sa.Column("exercise_snapshot", JSONB), schema="training")
    op.execute("""
        CREATE FUNCTION training.snapshot_exercise(p_revision_id uuid)
        RETURNS jsonb LANGUAGE sql STABLE AS $$
            SELECT jsonb_build_object(
                'revision', to_jsonb(r),
                'exercise', to_jsonb(e),
                'card_details', to_jsonb(d),
                'event_class', to_jsonb(ec),
                'additional_values', COALESCE((
                    SELECT jsonb_agg(to_jsonb(v) ORDER BY v.display_order, v.field_key)
                    FROM content.exercise_additional_values AS v
                    WHERE v.exercise_revision_id = r.id
                ), '[]'::jsonb),
                'service_ids', COALESCE((
                    SELECT jsonb_agg(es.service_id ORDER BY es.service_id)
                    FROM content.exercise_services AS es WHERE es.exercise_id = e.id
                ), '[]'::jsonb)
            )
            FROM content.exercise_revisions AS r
            JOIN content.exercises AS e ON e.id = r.exercise_id
            LEFT JOIN content.incident_card_details AS d ON d.exercise_revision_id = r.id
            LEFT JOIN catalog.event_classes AS ec ON ec.id = r.event_class_id
            WHERE r.id = p_revision_id
        $$
    """)
    op.execute("""
        UPDATE training.session_cards AS sc
        SET exercise_revision_id_snapshot = sc.exercise_revision_id,
            exercise_snapshot = training.snapshot_exercise(sc.exercise_revision_id)
    """)
    op.alter_column("session_cards", "exercise_revision_id_snapshot", nullable=False, schema="training")
    op.alter_column("session_cards", "exercise_snapshot", nullable=False, schema="training")
    op.create_check_constraint("ck_session_cards_exercise_snapshot_object", "session_cards", "jsonb_typeof(exercise_snapshot) = 'object'", schema="training")
    op.drop_constraint("fk_session_cards_exercise_revision_id_exercise_revisions", "session_cards", schema="training", type_="foreignkey")
    op.alter_column("session_cards", "exercise_revision_id", existing_type=UUID, nullable=True, schema="training")
    op.create_foreign_key("fk_session_cards_exercise_revision_id_exercise_revisions", "session_cards", "exercise_revisions", ["exercise_revision_id"], ["id"], source_schema="training", referent_schema="content", ondelete="SET NULL")
    op.create_index("ix_session_cards_exercise_revision_id", "session_cards", ["exercise_revision_id"], schema="training")
    op.execute("""
        CREATE FUNCTION training.capture_card_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.exercise_revision_id IS DISTINCT FROM OLD.exercise_revision_id THEN
                IF NEW.exercise_revision_id IS NULL THEN
                    IF TG_OP = 'INSERT' THEN
                        RAISE EXCEPTION 'New session card requires an exercise revision';
                    END IF;
                    RETURN NEW; -- FK SET NULL after source deletion: keep the snapshot.
                END IF;
                IF TG_OP = 'UPDATE' AND OLD.status <> 'pending' THEN
                    RAISE EXCEPTION 'A shown session card cannot be replaced';
                END IF;
                NEW.exercise_revision_id_snapshot := NEW.exercise_revision_id;
                NEW.exercise_snapshot := training.snapshot_exercise(NEW.exercise_revision_id);
                IF NEW.exercise_snapshot IS NULL THEN
                    RAISE EXCEPTION 'Exercise revision % does not exist', NEW.exercise_revision_id;
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_session_cards_capture_snapshot
        BEFORE INSERT OR UPDATE OF exercise_revision_id ON training.session_cards
        FOR EACH ROW EXECUTE FUNCTION training.capture_card_snapshot()
    """)

    # Prevent direct or cascading removal of submitted results.
    op.execute("""
        CREATE FUNCTION training.prevent_result_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Training answers and evaluations are retained permanently';
        END $$
    """)
    for table in ("answers", "evaluations"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_retain_result BEFORE DELETE ON training.{table} "
            "FOR EACH ROW EXECUTE FUNCTION training.prevent_result_delete()"
        )

    # The pre-existing six-month cleanup must never attempt to delete sessions
    # containing answers. Empty/draft sessions may still be cleaned up.
    op.execute("""
        CREATE OR REPLACE FUNCTION audit.purge_expired_data(p_limit integer DEFAULT 1000)
        RETURNS TABLE(entity_name text, deleted_count bigint)
        LANGUAGE plpgsql AS $$
        DECLARE affected bigint;
        BEGIN
            DELETE FROM training.sessions WHERE id IN (
                SELECT s.id FROM training.sessions AS s
                WHERE s.purge_after <= CURRENT_TIMESTAMP
                  AND NOT EXISTS (
                      SELECT 1 FROM training.session_cards AS sc
                      JOIN training.answers AS a ON a.session_card_id = sc.id
                      WHERE sc.session_id = s.id
                  )
                ORDER BY s.purge_after LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'training.sessions'::text, affected;

            DELETE FROM content.exercises WHERE id IN (
                SELECT id FROM content.exercises
                WHERE purge_after <= CURRENT_TIMESTAMP
                ORDER BY purge_after LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'content.exercises'::text, affected;

            DELETE FROM content.event_templates WHERE id IN (
                SELECT id FROM content.event_templates
                WHERE purge_after <= CURRENT_TIMESTAMP
                ORDER BY purge_after LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'content.event_templates'::text, affected;

            DELETE FROM training.scoring_profiles WHERE id IN (
                SELECT id FROM training.scoring_profiles
                WHERE purge_after <= CURRENT_TIMESTAMP
                ORDER BY purge_after LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'training.scoring_profiles'::text, affected;

            DELETE FROM catalog.services WHERE id IN (
                SELECT id FROM catalog.services
                WHERE purge_after <= CURRENT_TIMESTAMP
                ORDER BY purge_after LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'catalog.services'::text, affected;

            DELETE FROM catalog.event_classes WHERE id IN (
                SELECT id FROM catalog.event_classes
                WHERE purge_after <= CURRENT_TIMESTAMP
                ORDER BY purge_after LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'catalog.event_classes'::text, affected;

            DELETE FROM auth.users WHERE id IN (
                SELECT id FROM auth.users
                WHERE purge_after <= CURRENT_TIMESTAMP
                ORDER BY purge_after LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'auth.users'::text, affected;

            DELETE FROM audit.audit_log WHERE id IN (
                SELECT id FROM audit.audit_log
                WHERE retain_until <= CURRENT_TIMESTAMP
                ORDER BY retain_until LIMIT p_limit
            );
            GET DIAGNOSTICS affected = ROW_COUNT;
            RETURN QUERY SELECT 'audit.audit_log'::text, affected;
        END $$
    """)


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading permanent training-result retention could destroy historical answers"
    )
