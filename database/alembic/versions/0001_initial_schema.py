"""Initial database schema for the System-112 trainer.

Revision ID: 0001_initial_schema
Revises: None
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
RETENTION_CHECK = (
    "(deleted_at IS NULL AND purge_after IS NULL) OR "
    "(deleted_at IS NOT NULL AND purge_after IS NOT NULL "
    "AND purge_after >= deleted_at)"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def _retention() -> list[sa.Column]:
    return [
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    for schema in ("auth", "catalog", "content", "training", "audit"):
        op.execute(sa.schema.CreateSchema(schema))

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        *_retention(),
        sa.CheckConstraint(RETENTION_CHECK, name="retention_dates"),
        schema="auth",
    )
    op.create_table(
        "roles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_timestamps(),
        schema="auth",
    )
    op.create_table(
        "permissions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_timestamps(),
        schema="auth",
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", UUID, sa.ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", UUID, sa.ForeignKey("auth.roles.id", ondelete="CASCADE"), primary_key=True),
        schema="auth",
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID, sa.ForeignKey("auth.roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", UUID, sa.ForeignKey("auth.permissions.id", ondelete="CASCADE"), primary_key=True),
        schema="auth",
    )

    for table_name in ("event_classes", "services"):
        op.create_table(
            table_name,
            sa.Column("id", UUID, primary_key=True),
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            *_timestamps(),
            *_retention(),
            sa.CheckConstraint(RETENTION_CHECK, name="retention_dates"),
            schema="catalog",
        )

    op.create_table(
        "event_templates",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event_class_id", UUID, sa.ForeignKey("catalog.event_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("generation_instructions", sa.Text(), nullable=True),
        sa.Column("settings", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        *_retention(),
        sa.CheckConstraint(RETENTION_CHECK, name="retention_dates"),
        sa.CheckConstraint("status IN ('draft','review','approved','archived')", name="status_values"),
        sa.CheckConstraint("jsonb_typeof(settings) = 'object'", name="settings_object"),
        schema="content",
    )
    op.create_index(
        "ix_event_templates_active",
        "event_templates",
        ["event_class_id", "status"],
        schema="content",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "event_template_services",
        sa.Column("event_template_id", UUID, sa.ForeignKey("content.event_templates.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service_id", UUID, sa.ForeignKey("catalog.services.id", ondelete="CASCADE"), primary_key=True),
        schema="content",
    )
    op.create_table(
        "exercises",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event_template_id", UUID, sa.ForeignKey("content.event_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("difficulty", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("source", sa.String(16), server_default="ai_generated", nullable=False),
        sa.Column("active_revision_id", UUID, nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        *_retention(),
        sa.CheckConstraint(RETENTION_CHECK, name="retention_dates"),
        sa.CheckConstraint("difficulty IN ('easy','medium','hard')", name="difficulty_values"),
        sa.CheckConstraint("status IN ('draft','review','approved','rejected','archived')", name="status_values"),
        sa.CheckConstraint("source IN ('ai_generated','manual')", name="source_values"),
        schema="content",
    )
    op.create_index(
        "ix_exercises_bank_lookup",
        "exercises",
        ["difficulty", "status"],
        schema="content",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "exercise_revisions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("exercise_id", UUID, sa.ForeignKey("content.exercises.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("field_schema", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("source_payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("trainee_card", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("ethalon_payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("review_status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("change_comment", sa.Text(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("exercise_id", "revision_number", name="uq_exercise_revisions_exercise_id"),
        sa.CheckConstraint("revision_number > 0", name="revision_positive"),
        sa.CheckConstraint("review_status IN ('draft','review','approved','rejected','superseded')", name="review_status_values"),
        sa.CheckConstraint("jsonb_typeof(field_schema) = 'array'", name="field_schema_array"),
        sa.CheckConstraint("jsonb_typeof(source_payload) = 'object'", name="source_payload_object"),
        sa.CheckConstraint("jsonb_typeof(trainee_card) = 'object'", name="trainee_card_object"),
        sa.CheckConstraint("jsonb_typeof(ethalon_payload) = 'object'", name="ethalon_payload_object"),
        schema="content",
    )
    op.create_index("ix_exercise_revisions_source_gin", "exercise_revisions", ["source_payload"], schema="content", postgresql_using="gin")
    op.create_index("ix_exercise_revisions_ethalon_gin", "exercise_revisions", ["ethalon_payload"], schema="content", postgresql_using="gin")
    op.create_foreign_key(
        "fk_exercises_active_revision",
        "exercises",
        "exercise_revisions",
        ["active_revision_id"],
        ["id"],
        source_schema="content",
        referent_schema="content",
        ondelete="SET NULL",
    )
    op.create_table(
        "exercise_services",
        sa.Column("exercise_id", UUID, sa.ForeignKey("content.exercises.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service_id", UUID, sa.ForeignKey("catalog.services.id", ondelete="CASCADE"), primary_key=True),
        schema="content",
    )

    op.create_table(
        "scoring_profiles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        *_retention(),
        sa.CheckConstraint(RETENTION_CHECK, name="retention_dates"),
        schema="training",
    )
    op.create_table(
        "scoring_rules",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("profile_id", UUID, sa.ForeignKey("training.scoring_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("difficulty", sa.String(16), nullable=False),
        sa.Column("correctness_threshold", sa.Numeric(5, 2), nullable=False),
        sa.Column("half_life_seconds", sa.Integer(), nullable=False),
        sa.Column("min_time_factor", sa.Numeric(4, 3), nullable=False),
        sa.Column("max_score", sa.Numeric(7, 2), nullable=False),
        sa.UniqueConstraint("profile_id", "difficulty", name="uq_scoring_rules_profile_id"),
        sa.CheckConstraint("difficulty IN ('easy','medium','hard')", name="difficulty_values"),
        sa.CheckConstraint("correctness_threshold BETWEEN 0 AND 100", name="threshold_range"),
        sa.CheckConstraint("half_life_seconds > 0", name="half_life_positive"),
        sa.CheckConstraint("min_time_factor BETWEEN 0 AND 1", name="min_time_factor_range"),
        sa.CheckConstraint("max_score > 0", name="max_score_positive"),
        schema="training",
    )
    op.create_table(
        "sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("trainee_id", UUID, sa.ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scoring_profile_id", UUID, sa.ForeignKey("training.scoring_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_card_count", sa.Integer(), nullable=False),
        sa.Column("starting_difficulty", sa.String(16), nullable=False),
        sa.Column("current_difficulty", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("scoring_snapshot", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        *_retention(),
        sa.CheckConstraint(RETENTION_CHECK, name="retention_dates"),
        sa.CheckConstraint("requested_card_count > 0", name="card_count_positive"),
        sa.CheckConstraint("starting_difficulty IN ('easy','medium','hard')", name="starting_difficulty_values"),
        sa.CheckConstraint("current_difficulty IN ('easy','medium','hard')", name="current_difficulty_values"),
        sa.CheckConstraint("status IN ('draft','active','completed','cancelled')", name="status_values"),
        sa.CheckConstraint("jsonb_typeof(scoring_snapshot) = 'object'", name="scoring_snapshot_object"),
        schema="training",
    )
    op.create_index(
        "ix_sessions_trainee_status",
        "sessions",
        ["trainee_id", "status"],
        schema="training",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "session_cards",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("session_id", UUID, sa.ForeignKey("training.sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_revision_id", UUID, sa.ForeignKey("content.exercise_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("difficulty_snapshot", sa.String(16), nullable=False),
        sa.Column("is_repeat", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_session_cards_session_id"),
        sa.CheckConstraint("sequence_number > 0", name="sequence_positive"),
        sa.CheckConstraint("difficulty_snapshot IN ('easy','medium','hard')", name="difficulty_values"),
        sa.CheckConstraint("status IN ('pending','shown','submitted','evaluated')", name="status_values"),
        schema="training",
    )
    op.create_index("ix_session_cards_session_sequence", "session_cards", ["session_id", "sequence_number"], schema="training")
    op.create_table(
        "answers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("session_card_id", UUID, sa.ForeignKey("training.session_cards.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        schema="training",
    )
    op.create_table(
        "evaluations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("answer_id", UUID, sa.ForeignKey("training.answers.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("accuracy_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("threshold_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("time_factor", sa.Numeric(6, 5), nullable=False),
        sa.Column("accuracy_score", sa.Numeric(7, 2), nullable=False),
        sa.Column("total_score", sa.Numeric(7, 2), nullable=False),
        sa.Column("current_difficulty", sa.String(16), nullable=False),
        sa.Column("next_difficulty", sa.String(16), nullable=False),
        sa.Column("details", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("scoring_rule_snapshot", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("accuracy_percent BETWEEN 0 AND 100", name="accuracy_range"),
        sa.CheckConstraint("threshold_percent BETWEEN 0 AND 100", name="threshold_range"),
        sa.CheckConstraint("time_factor BETWEEN 0 AND 1", name="time_factor_range"),
        sa.CheckConstraint("accuracy_score >= 0", name="accuracy_score_nonnegative"),
        sa.CheckConstraint("total_score >= 0", name="total_score_nonnegative"),
        sa.CheckConstraint("current_difficulty IN ('easy','medium','hard')", name="current_difficulty_values"),
        sa.CheckConstraint("next_difficulty IN ('easy','medium','hard')", name="next_difficulty_values"),
        sa.CheckConstraint("jsonb_typeof(details) = 'object'", name="details_object"),
        sa.CheckConstraint("jsonb_typeof(scoring_rule_snapshot) = 'object'", name="scoring_rule_snapshot_object"),
        schema="training",
    )

    op.create_table(
        "audit_log",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("auth.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("entity_id", UUID, nullable=True),
        sa.Column("payload", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP + INTERVAL '6 months'"), nullable=False),
        schema="audit",
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], schema="audit")
    op.create_index("ix_audit_log_actor_created", "audit_log", ["actor_id", "created_at"], schema="audit")
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], schema="audit")

    _create_scoring_functions()
    _create_maintenance_functions()
    _seed_default_scoring_profile()


def _create_scoring_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION training.calculate_time_factor(
            p_duration_ms bigint,
            p_half_life_seconds integer,
            p_min_time_factor numeric
        ) RETURNS numeric
        LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT p_min_time_factor
                + (1 - p_min_time_factor)
                * power(
                    2::numeric,
                    -((p_duration_ms::numeric / 1000) / p_half_life_seconds)
                  )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION training.calculate_total_score(
            p_accuracy_percent numeric,
            p_duration_ms bigint,
            p_half_life_seconds integer,
            p_min_time_factor numeric,
            p_max_score numeric
        ) RETURNS numeric
        LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT round(
                p_max_score
                * (p_accuracy_percent / 100)
                * training.calculate_time_factor(
                    p_duration_ms,
                    p_half_life_seconds,
                    p_min_time_factor
                  ),
                2
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION training.next_difficulty(
            p_current_difficulty text,
            p_is_correct boolean
        ) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT CASE
                WHEN p_is_correct THEN p_current_difficulty
                WHEN p_current_difficulty = 'hard' THEN 'medium'
                ELSE 'easy'
            END
        $$
        """
    )


def _create_maintenance_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION audit.assign_retention_deadline()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
                NEW.purge_after := NEW.deleted_at + INTERVAL '6 months';
            ELSIF NEW.deleted_at IS NULL THEN
                NEW.purge_after := NULL;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION audit.touch_updated_at()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$
        """
    )

    retained_tables = (
        ("auth", "users"),
        ("catalog", "event_classes"),
        ("catalog", "services"),
        ("content", "event_templates"),
        ("content", "exercises"),
        ("training", "scoring_profiles"),
        ("training", "sessions"),
    )
    updated_tables = (
        ("auth", "users"),
        ("auth", "roles"),
        ("auth", "permissions"),
        ("catalog", "event_classes"),
        ("catalog", "services"),
        ("content", "event_templates"),
        ("content", "exercises"),
        ("training", "scoring_profiles"),
        ("training", "sessions"),
    )
    for schema, table in retained_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_retention "
            f"BEFORE UPDATE OF deleted_at ON {schema}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline()"
        )
    for schema, table in updated_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at "
            f"BEFORE UPDATE ON {schema}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at()"
        )

    op.execute(
        """
        CREATE FUNCTION audit.purge_expired_data(p_limit integer DEFAULT 1000)
        RETURNS TABLE(entity_name text, deleted_count bigint)
        LANGUAGE plpgsql AS $$
        DECLARE affected bigint;
        BEGIN
            DELETE FROM training.sessions WHERE id IN (
                SELECT id FROM training.sessions
                WHERE purge_after <= CURRENT_TIMESTAMP
                ORDER BY purge_after LIMIT p_limit
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
        END;
        $$
        """
    )


def _seed_default_scoring_profile() -> None:
    profile_id = "00000000-0000-0000-0000-000000000001"
    op.execute(
        sa.text(
            """
            INSERT INTO training.scoring_profiles
                (id, name, description, is_default)
            VALUES
                (CAST(:profile_id AS uuid), 'Default adaptive scoring',
                 'Thresholds and exponential time decay approved for the initial schema', true)
            """
        ).bindparams(profile_id=profile_id)
    )
    rules = (
        ("00000000-0000-0000-0000-000000000011", "easy", 70, 60),
        ("00000000-0000-0000-0000-000000000012", "medium", 80, 120),
        ("00000000-0000-0000-0000-000000000013", "hard", 90, 180),
    )
    for rule_id, difficulty, threshold, half_life in rules:
        op.execute(
            sa.text(
                """
                INSERT INTO training.scoring_rules
                    (id, profile_id, difficulty, correctness_threshold,
                     half_life_seconds, min_time_factor, max_score)
                VALUES
                    (CAST(:rule_id AS uuid), CAST(:profile_id AS uuid), :difficulty,
                     :threshold, :half_life, 0.300, 100.00)
                """
            ).bindparams(
                rule_id=rule_id,
                profile_id=profile_id,
                difficulty=difficulty,
                threshold=threshold,
                half_life=half_life,
            )
        )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS audit.purge_expired_data(integer)")
    op.execute("DROP FUNCTION IF EXISTS audit.touch_updated_at() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS audit.assign_retention_deadline() CASCADE")
    op.execute("DROP FUNCTION IF EXISTS training.next_difficulty(text, boolean)")
    op.execute("DROP FUNCTION IF EXISTS training.calculate_total_score(numeric, bigint, integer, numeric, numeric)")
    op.execute("DROP FUNCTION IF EXISTS training.calculate_time_factor(bigint, integer, numeric)")
    for schema in ("audit", "training", "content", "catalog", "auth"):
        op.execute(sa.schema.DropSchema(schema, cascade=True))
