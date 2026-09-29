CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_users (
    id bigserial PRIMARY KEY,
    login varchar(64) NOT NULL,
    full_name varchar(160) NOT NULL,
    role varchar(16) NOT NULL CHECK (role IN ('admin','teacher','student')),
    salt bytea NOT NULL,
    password_hash bytea NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT app_users_login_normalized CHECK (login = lower(login)),
    CONSTRAINT app_users_login_unique UNIQUE (login),
    CONSTRAINT app_users_full_name_unique UNIQUE (full_name)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id uuid PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);

CREATE TABLE IF NOT EXISTS engine_items (
    id varchar(32) PRIMARY KEY,
    kind char(1) NOT NULL CHECK (kind IN ('t','s')),
    status varchar(32),
    student varchar(160),
    task_id varchar(32),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS curriculum_resources (
    id varchar(40) PRIMARY KEY,
    kind varchar(16) NOT NULL CHECK (kind IN ('scenario','training')),
    status varchar(32) NOT NULL,
    title varchar(160) NOT NULL DEFAULT '',
    teacher varchar(160),
    room_code varchar(16),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS training_participants (
    training_id varchar(40) NOT NULL REFERENCES curriculum_resources(id) ON DELETE CASCADE,
    participant_id varchar(32) NOT NULL,
    user_id bigint REFERENCES app_users(id) ON DELETE SET NULL,
    student_name varchar(160) NOT NULL,
    training_role varchar(16) NOT NULL CHECK (training_role IN ('waiting','operator','dds','service')),
    service varchar(32) NOT NULL DEFAULT '',
    joined_at timestamptz NOT NULL,
    PRIMARY KEY (training_id, participant_id),
    UNIQUE (training_id, student_name)
);

CREATE TABLE IF NOT EXISTS training_cards (
    training_id varchar(40) NOT NULL REFERENCES curriculum_resources(id) ON DELETE CASCADE,
    card_id varchar(32) NOT NULL,
    operator_session_id varchar(32),
    task_id varchar(32),
    student_name varchar(160),
    status varchar(32) NOT NULL,
    dds_by varchar(160),
    submitted_at timestamptz,
    routed_at timestamptz,
    updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (training_id, card_id)
);

CREATE TABLE IF NOT EXISTS training_events (
    id bigserial PRIMARY KEY,
    training_id varchar(40) NOT NULL REFERENCES curriculum_resources(id) ON DELETE CASCADE,
    card_id varchar(32),
    actor varchar(160),
    event_type varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS materials (
    id varchar(40) PRIMARY KEY,
    title varchar(160) NOT NULL,
    url text NOT NULL,
    description varchar(1000) NOT NULL DEFAULT '',
    teacher varchar(160) NOT NULL,
    created_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);
