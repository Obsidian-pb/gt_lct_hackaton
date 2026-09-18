BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_initial_schema

CREATE SCHEMA auth;

CREATE SCHEMA catalog;

CREATE SCHEMA content;

CREATE SCHEMA training;

CREATE SCHEMA audit;

CREATE TABLE auth.users (
    id UUID NOT NULL, 
    username VARCHAR(100) NOT NULL, 
    email VARCHAR(320), 
    password_hash VARCHAR(255), 
    display_name VARCHAR(255) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    purge_after TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT ck_users_retention_dates CHECK ((deleted_at IS NULL AND purge_after IS NULL) OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)), 
    CONSTRAINT uq_users_username UNIQUE (username), 
    CONSTRAINT uq_users_email UNIQUE (email)
);

CREATE TABLE auth.roles (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    name VARCHAR(128) NOT NULL, 
    description TEXT, 
    is_system BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    CONSTRAINT pk_roles PRIMARY KEY (id), 
    CONSTRAINT uq_roles_code UNIQUE (code)
);

CREATE TABLE auth.permissions (
    id UUID NOT NULL, 
    code VARCHAR(128) NOT NULL, 
    name VARCHAR(128) NOT NULL, 
    description TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    CONSTRAINT pk_permissions PRIMARY KEY (id), 
    CONSTRAINT uq_permissions_code UNIQUE (code)
);

CREATE TABLE auth.user_roles (
    user_id UUID NOT NULL, 
    role_id UUID NOT NULL, 
    CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id), 
    CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY(user_id) REFERENCES auth.users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY(role_id) REFERENCES auth.roles (id) ON DELETE CASCADE
);

CREATE TABLE auth.role_permissions (
    role_id UUID NOT NULL, 
    permission_id UUID NOT NULL, 
    CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id), 
    CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY(role_id) REFERENCES auth.roles (id) ON DELETE CASCADE, 
    CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES auth.permissions (id) ON DELETE CASCADE
);

CREATE TABLE catalog.event_classes (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    description TEXT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    purge_after TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_event_classes PRIMARY KEY (id), 
    CONSTRAINT ck_event_classes_retention_dates CHECK ((deleted_at IS NULL AND purge_after IS NULL) OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)), 
    CONSTRAINT uq_event_classes_code UNIQUE (code)
);

CREATE TABLE catalog.services (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    description TEXT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    purge_after TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_services PRIMARY KEY (id), 
    CONSTRAINT ck_services_retention_dates CHECK ((deleted_at IS NULL AND purge_after IS NULL) OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)), 
    CONSTRAINT uq_services_code UNIQUE (code)
);

CREATE TABLE content.event_templates (
    id UUID NOT NULL, 
    event_class_id UUID NOT NULL, 
    topic VARCHAR(255) NOT NULL, 
    description TEXT, 
    generation_instructions TEXT, 
    settings JSONB DEFAULT '{}'::jsonb NOT NULL, 
    status VARCHAR(16) DEFAULT 'draft' NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    purge_after TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_event_templates PRIMARY KEY (id), 
    CONSTRAINT ck_event_templates_retention_dates CHECK ((deleted_at IS NULL AND purge_after IS NULL) OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)), 
    CONSTRAINT ck_event_templates_status_values CHECK (status IN ('draft','review','approved','archived')), 
    CONSTRAINT ck_event_templates_settings_object CHECK (jsonb_typeof(settings) = 'object'), 
    CONSTRAINT fk_event_templates_event_class_id_event_classes FOREIGN KEY(event_class_id) REFERENCES catalog.event_classes (id) ON DELETE CASCADE, 
    CONSTRAINT fk_event_templates_created_by_users FOREIGN KEY(created_by) REFERENCES auth.users (id) ON DELETE SET NULL
);

CREATE INDEX ix_event_templates_active ON content.event_templates (event_class_id, status) WHERE deleted_at IS NULL;

CREATE TABLE content.event_template_services (
    event_template_id UUID NOT NULL, 
    service_id UUID NOT NULL, 
    CONSTRAINT pk_event_template_services PRIMARY KEY (event_template_id, service_id), 
    CONSTRAINT fk_event_template_services_event_template_id_event_templates FOREIGN KEY(event_template_id) REFERENCES content.event_templates (id) ON DELETE CASCADE, 
    CONSTRAINT fk_event_template_services_service_id_services FOREIGN KEY(service_id) REFERENCES catalog.services (id) ON DELETE CASCADE
);

CREATE TABLE content.exercises (
    id UUID NOT NULL, 
    event_template_id UUID NOT NULL, 
    difficulty VARCHAR(16) NOT NULL, 
    status VARCHAR(16) DEFAULT 'draft' NOT NULL, 
    source VARCHAR(16) DEFAULT 'ai_generated' NOT NULL, 
    active_revision_id UUID, 
    created_by UUID, 
    approved_by UUID, 
    approved_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    purge_after TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_exercises PRIMARY KEY (id), 
    CONSTRAINT ck_exercises_retention_dates CHECK ((deleted_at IS NULL AND purge_after IS NULL) OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)), 
    CONSTRAINT ck_exercises_difficulty_values CHECK (difficulty IN ('easy','medium','hard')), 
    CONSTRAINT ck_exercises_status_values CHECK (status IN ('draft','review','approved','rejected','archived')), 
    CONSTRAINT ck_exercises_source_values CHECK (source IN ('ai_generated','manual')), 
    CONSTRAINT fk_exercises_event_template_id_event_templates FOREIGN KEY(event_template_id) REFERENCES content.event_templates (id) ON DELETE CASCADE, 
    CONSTRAINT fk_exercises_created_by_users FOREIGN KEY(created_by) REFERENCES auth.users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_exercises_approved_by_users FOREIGN KEY(approved_by) REFERENCES auth.users (id) ON DELETE SET NULL
);

CREATE INDEX ix_exercises_bank_lookup ON content.exercises (difficulty, status) WHERE deleted_at IS NULL;

CREATE TABLE content.exercise_revisions (
    id UUID NOT NULL, 
    exercise_id UUID NOT NULL, 
    revision_number INTEGER NOT NULL, 
    field_schema JSONB DEFAULT '[]'::jsonb NOT NULL, 
    source_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    trainee_card JSONB DEFAULT '{}'::jsonb NOT NULL, 
    ethalon_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    review_status VARCHAR(16) DEFAULT 'draft' NOT NULL, 
    change_comment TEXT, 
    review_comment TEXT, 
    created_by UUID, 
    reviewed_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    reviewed_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_exercise_revisions PRIMARY KEY (id), 
    CONSTRAINT uq_exercise_revisions_exercise_id UNIQUE (exercise_id, revision_number), 
    CONSTRAINT ck_exercise_revisions_revision_positive CHECK (revision_number > 0), 
    CONSTRAINT ck_exercise_revisions_review_status_values CHECK (review_status IN ('draft','review','approved','rejected','superseded')), 
    CONSTRAINT ck_exercise_revisions_field_schema_array CHECK (jsonb_typeof(field_schema) = 'array'), 
    CONSTRAINT ck_exercise_revisions_source_payload_object CHECK (jsonb_typeof(source_payload) = 'object'), 
    CONSTRAINT ck_exercise_revisions_trainee_card_object CHECK (jsonb_typeof(trainee_card) = 'object'), 
    CONSTRAINT ck_exercise_revisions_ethalon_payload_object CHECK (jsonb_typeof(ethalon_payload) = 'object'), 
    CONSTRAINT fk_exercise_revisions_exercise_id_exercises FOREIGN KEY(exercise_id) REFERENCES content.exercises (id) ON DELETE CASCADE, 
    CONSTRAINT fk_exercise_revisions_created_by_users FOREIGN KEY(created_by) REFERENCES auth.users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_exercise_revisions_reviewed_by_users FOREIGN KEY(reviewed_by) REFERENCES auth.users (id) ON DELETE SET NULL
);

CREATE INDEX ix_exercise_revisions_source_gin ON content.exercise_revisions USING gin (source_payload);

CREATE INDEX ix_exercise_revisions_ethalon_gin ON content.exercise_revisions USING gin (ethalon_payload);

ALTER TABLE content.exercises ADD CONSTRAINT fk_exercises_active_revision FOREIGN KEY(active_revision_id) REFERENCES content.exercise_revisions (id) ON DELETE SET NULL;

CREATE TABLE content.exercise_services (
    exercise_id UUID NOT NULL, 
    service_id UUID NOT NULL, 
    CONSTRAINT pk_exercise_services PRIMARY KEY (exercise_id, service_id), 
    CONSTRAINT fk_exercise_services_exercise_id_exercises FOREIGN KEY(exercise_id) REFERENCES content.exercises (id) ON DELETE CASCADE, 
    CONSTRAINT fk_exercise_services_service_id_services FOREIGN KEY(service_id) REFERENCES catalog.services (id) ON DELETE CASCADE
);

CREATE TABLE training.scoring_profiles (
    id UUID NOT NULL, 
    name VARCHAR(255) NOT NULL, 
    description TEXT, 
    is_default BOOLEAN DEFAULT false NOT NULL, 
    created_by UUID, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    purge_after TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_scoring_profiles PRIMARY KEY (id), 
    CONSTRAINT ck_scoring_profiles_retention_dates CHECK ((deleted_at IS NULL AND purge_after IS NULL) OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)), 
    CONSTRAINT uq_scoring_profiles_name UNIQUE (name), 
    CONSTRAINT fk_scoring_profiles_created_by_users FOREIGN KEY(created_by) REFERENCES auth.users (id) ON DELETE SET NULL
);

CREATE TABLE training.scoring_rules (
    id UUID NOT NULL, 
    profile_id UUID NOT NULL, 
    difficulty VARCHAR(16) NOT NULL, 
    correctness_threshold NUMERIC(5, 2) NOT NULL, 
    half_life_seconds INTEGER NOT NULL, 
    min_time_factor NUMERIC(4, 3) NOT NULL, 
    max_score NUMERIC(7, 2) NOT NULL, 
    CONSTRAINT pk_scoring_rules PRIMARY KEY (id), 
    CONSTRAINT uq_scoring_rules_profile_id UNIQUE (profile_id, difficulty), 
    CONSTRAINT ck_scoring_rules_difficulty_values CHECK (difficulty IN ('easy','medium','hard')), 
    CONSTRAINT ck_scoring_rules_threshold_range CHECK (correctness_threshold BETWEEN 0 AND 100), 
    CONSTRAINT ck_scoring_rules_half_life_positive CHECK (half_life_seconds > 0), 
    CONSTRAINT ck_scoring_rules_min_time_factor_range CHECK (min_time_factor BETWEEN 0 AND 1), 
    CONSTRAINT ck_scoring_rules_max_score_positive CHECK (max_score > 0), 
    CONSTRAINT fk_scoring_rules_profile_id_scoring_profiles FOREIGN KEY(profile_id) REFERENCES training.scoring_profiles (id) ON DELETE CASCADE
);

CREATE TABLE training.sessions (
    id UUID NOT NULL, 
    trainee_id UUID NOT NULL, 
    teacher_id UUID, 
    scoring_profile_id UUID, 
    requested_card_count INTEGER NOT NULL, 
    starting_difficulty VARCHAR(16) NOT NULL, 
    current_difficulty VARCHAR(16) NOT NULL, 
    status VARCHAR(16) DEFAULT 'draft' NOT NULL, 
    scoring_snapshot JSONB DEFAULT '{}'::jsonb NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    purge_after TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_sessions PRIMARY KEY (id), 
    CONSTRAINT ck_sessions_retention_dates CHECK ((deleted_at IS NULL AND purge_after IS NULL) OR (deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after >= deleted_at)), 
    CONSTRAINT ck_sessions_card_count_positive CHECK (requested_card_count > 0), 
    CONSTRAINT ck_sessions_starting_difficulty_values CHECK (starting_difficulty IN ('easy','medium','hard')), 
    CONSTRAINT ck_sessions_current_difficulty_values CHECK (current_difficulty IN ('easy','medium','hard')), 
    CONSTRAINT ck_sessions_status_values CHECK (status IN ('draft','active','completed','cancelled')), 
    CONSTRAINT ck_sessions_scoring_snapshot_object CHECK (jsonb_typeof(scoring_snapshot) = 'object'), 
    CONSTRAINT fk_sessions_trainee_id_users FOREIGN KEY(trainee_id) REFERENCES auth.users (id) ON DELETE CASCADE, 
    CONSTRAINT fk_sessions_teacher_id_users FOREIGN KEY(teacher_id) REFERENCES auth.users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_sessions_scoring_profile_id_scoring_profiles FOREIGN KEY(scoring_profile_id) REFERENCES training.scoring_profiles (id) ON DELETE SET NULL
);

CREATE INDEX ix_sessions_trainee_status ON training.sessions (trainee_id, status) WHERE deleted_at IS NULL;

CREATE TABLE training.session_cards (
    id UUID NOT NULL, 
    session_id UUID NOT NULL, 
    exercise_revision_id UUID NOT NULL, 
    sequence_number INTEGER NOT NULL, 
    difficulty_snapshot VARCHAR(16) NOT NULL, 
    is_repeat BOOLEAN DEFAULT false NOT NULL, 
    status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
    shown_at TIMESTAMP WITH TIME ZONE, 
    submitted_at TIMESTAMP WITH TIME ZONE, 
    duration_ms INTEGER, 
    CONSTRAINT pk_session_cards PRIMARY KEY (id), 
    CONSTRAINT uq_session_cards_session_id UNIQUE (session_id, sequence_number), 
    CONSTRAINT ck_session_cards_sequence_positive CHECK (sequence_number > 0), 
    CONSTRAINT ck_session_cards_difficulty_values CHECK (difficulty_snapshot IN ('easy','medium','hard')), 
    CONSTRAINT ck_session_cards_status_values CHECK (status IN ('pending','shown','submitted','evaluated')), 
    CONSTRAINT fk_session_cards_session_id_sessions FOREIGN KEY(session_id) REFERENCES training.sessions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_session_cards_exercise_revision_id_exercise_revisions FOREIGN KEY(exercise_revision_id) REFERENCES content.exercise_revisions (id) ON DELETE CASCADE
);

CREATE INDEX ix_session_cards_session_sequence ON training.session_cards (session_id, sequence_number);

CREATE TABLE training.answers (
    id UUID NOT NULL, 
    session_card_id UUID NOT NULL, 
    payload JSONB NOT NULL, 
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    CONSTRAINT pk_answers PRIMARY KEY (id), 
    CONSTRAINT ck_answers_payload_object CHECK (jsonb_typeof(payload) = 'object'), 
    CONSTRAINT uq_answers_session_card_id UNIQUE (session_card_id), 
    CONSTRAINT fk_answers_session_card_id_session_cards FOREIGN KEY(session_card_id) REFERENCES training.session_cards (id) ON DELETE CASCADE
);

CREATE TABLE training.evaluations (
    id UUID NOT NULL, 
    answer_id UUID NOT NULL, 
    accuracy_percent NUMERIC(5, 2) NOT NULL, 
    threshold_percent NUMERIC(5, 2) NOT NULL, 
    is_correct BOOLEAN NOT NULL, 
    duration_ms INTEGER NOT NULL, 
    time_factor NUMERIC(6, 5) NOT NULL, 
    accuracy_score NUMERIC(7, 2) NOT NULL, 
    total_score NUMERIC(7, 2) NOT NULL, 
    current_difficulty VARCHAR(16) NOT NULL, 
    next_difficulty VARCHAR(16) NOT NULL, 
    details JSONB DEFAULT '{}'::jsonb NOT NULL, 
    scoring_rule_snapshot JSONB DEFAULT '{}'::jsonb NOT NULL, 
    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    CONSTRAINT pk_evaluations PRIMARY KEY (id), 
    CONSTRAINT ck_evaluations_accuracy_range CHECK (accuracy_percent BETWEEN 0 AND 100), 
    CONSTRAINT ck_evaluations_threshold_range CHECK (threshold_percent BETWEEN 0 AND 100), 
    CONSTRAINT ck_evaluations_time_factor_range CHECK (time_factor BETWEEN 0 AND 1), 
    CONSTRAINT ck_evaluations_accuracy_score_nonnegative CHECK (accuracy_score >= 0), 
    CONSTRAINT ck_evaluations_total_score_nonnegative CHECK (total_score >= 0), 
    CONSTRAINT ck_evaluations_current_difficulty_values CHECK (current_difficulty IN ('easy','medium','hard')), 
    CONSTRAINT ck_evaluations_next_difficulty_values CHECK (next_difficulty IN ('easy','medium','hard')), 
    CONSTRAINT ck_evaluations_details_object CHECK (jsonb_typeof(details) = 'object'), 
    CONSTRAINT ck_evaluations_scoring_rule_snapshot_object CHECK (jsonb_typeof(scoring_rule_snapshot) = 'object'), 
    CONSTRAINT uq_evaluations_answer_id UNIQUE (answer_id), 
    CONSTRAINT fk_evaluations_answer_id_answers FOREIGN KEY(answer_id) REFERENCES training.answers (id) ON DELETE CASCADE
);

CREATE TABLE audit.audit_log (
    id UUID NOT NULL, 
    actor_id UUID, 
    action VARCHAR(128) NOT NULL, 
    entity_type VARCHAR(128) NOT NULL, 
    entity_id UUID, 
    payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
    retain_until TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP + INTERVAL '6 months' NOT NULL, 
    CONSTRAINT pk_audit_log PRIMARY KEY (id), 
    CONSTRAINT fk_audit_log_actor_id_users FOREIGN KEY(actor_id) REFERENCES auth.users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_log_created_at ON audit.audit_log (created_at);

CREATE INDEX ix_audit_log_actor_created ON audit.audit_log (actor_id, created_at);

CREATE INDEX ix_audit_log_entity ON audit.audit_log (entity_type, entity_id);

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
        $$;

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
        $$;

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
        $$;

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
        $$;

CREATE FUNCTION audit.touch_updated_at()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := CURRENT_TIMESTAMP;
            RETURN NEW;
        END;
        $$;

CREATE TRIGGER trg_users_retention BEFORE UPDATE OF deleted_at ON auth.users FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline();

CREATE TRIGGER trg_event_classes_retention BEFORE UPDATE OF deleted_at ON catalog.event_classes FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline();

CREATE TRIGGER trg_services_retention BEFORE UPDATE OF deleted_at ON catalog.services FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline();

CREATE TRIGGER trg_event_templates_retention BEFORE UPDATE OF deleted_at ON content.event_templates FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline();

CREATE TRIGGER trg_exercises_retention BEFORE UPDATE OF deleted_at ON content.exercises FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline();

CREATE TRIGGER trg_scoring_profiles_retention BEFORE UPDATE OF deleted_at ON training.scoring_profiles FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline();

CREATE TRIGGER trg_sessions_retention BEFORE UPDATE OF deleted_at ON training.sessions FOR EACH ROW EXECUTE FUNCTION audit.assign_retention_deadline();

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON auth.users FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_roles_updated_at BEFORE UPDATE ON auth.roles FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_permissions_updated_at BEFORE UPDATE ON auth.permissions FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_event_classes_updated_at BEFORE UPDATE ON catalog.event_classes FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_services_updated_at BEFORE UPDATE ON catalog.services FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_event_templates_updated_at BEFORE UPDATE ON content.event_templates FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_exercises_updated_at BEFORE UPDATE ON content.exercises FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_scoring_profiles_updated_at BEFORE UPDATE ON training.scoring_profiles FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

CREATE TRIGGER trg_sessions_updated_at BEFORE UPDATE ON training.sessions FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at();

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
        $$;

INSERT INTO training.scoring_profiles
                (id, name, description, is_default)
            VALUES
                (CAST('00000000-0000-0000-0000-000000000001' AS uuid), 'Default adaptive scoring',
                 'Thresholds and exponential time decay approved for the initial schema', true);

INSERT INTO training.scoring_rules
                    (id, profile_id, difficulty, correctness_threshold,
                     half_life_seconds, min_time_factor, max_score)
                VALUES
                    (CAST('00000000-0000-0000-0000-000000000011' AS uuid), CAST('00000000-0000-0000-0000-000000000001' AS uuid), 'easy',
                     70, 60, 0.300, 100.00);

INSERT INTO training.scoring_rules
                    (id, profile_id, difficulty, correctness_threshold,
                     half_life_seconds, min_time_factor, max_score)
                VALUES
                    (CAST('00000000-0000-0000-0000-000000000012' AS uuid), CAST('00000000-0000-0000-0000-000000000001' AS uuid), 'medium',
                     80, 120, 0.300, 100.00);

INSERT INTO training.scoring_rules
                    (id, profile_id, difficulty, correctness_threshold,
                     half_life_seconds, min_time_factor, max_score)
                VALUES
                    (CAST('00000000-0000-0000-0000-000000000013' AS uuid), CAST('00000000-0000-0000-0000-000000000001' AS uuid), 'hard',
                     90, 180, 0.300, 100.00);

INSERT INTO alembic_version (version_num) VALUES ('0001_initial_schema') RETURNING alembic_version.version_num;

COMMIT;

