ALTER TABLE app_users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_active
    ON auth_sessions(token_hash, expires_at) WHERE revoked_at IS NULL;
