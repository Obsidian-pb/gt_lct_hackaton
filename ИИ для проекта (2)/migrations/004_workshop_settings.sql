CREATE TABLE IF NOT EXISTS workshop_states (
    user_id bigint PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS system_settings (
    key varchar(100) PRIMARY KEY,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_workshop_states_updated ON workshop_states(updated_at DESC);
