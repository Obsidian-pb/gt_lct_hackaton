CREATE INDEX IF NOT EXISTS idx_engine_items_kind_updated ON engine_items(kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_engine_items_student ON engine_items(student) WHERE student IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_engine_items_task ON engine_items(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_curriculum_kind_created ON curriculum_resources(kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_curriculum_teacher ON curriculum_resources(teacher) WHERE teacher IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_training_room_code ON curriculum_resources(room_code)
    WHERE kind='training' AND room_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_training_participants_user ON training_participants(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_training_participants_name ON training_participants(student_name);
CREATE INDEX IF NOT EXISTS idx_training_cards_status ON training_cards(training_id, status);
CREATE INDEX IF NOT EXISTS idx_training_cards_operator_session ON training_cards(operator_session_id)
    WHERE operator_session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_training_events_training_time ON training_events(training_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_training_events_card_time ON training_events(card_id, created_at DESC) WHERE card_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, expires_at DESC);
