CREATE TABLE IF NOT EXISTS scenario_tasks (
    scenario_id varchar(40) NOT NULL REFERENCES curriculum_resources(id) ON DELETE CASCADE,
    task_id varchar(32) NOT NULL,
    position integer NOT NULL,
    difficulty integer NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
    PRIMARY KEY (scenario_id, task_id)
);
CREATE TABLE IF NOT EXISTS training_scenarios (
    training_id varchar(40) NOT NULL REFERENCES curriculum_resources(id) ON DELETE CASCADE,
    scenario_id varchar(40) NOT NULL,
    position integer NOT NULL,
    PRIMARY KEY (training_id, scenario_id)
);
CREATE TABLE IF NOT EXISTS training_tasks (
    training_id varchar(40) NOT NULL REFERENCES curriculum_resources(id) ON DELETE CASCADE,
    task_id varchar(32) NOT NULL,
    position integer NOT NULL,
    PRIMARY KEY (training_id, task_id)
);
CREATE TABLE IF NOT EXISTS session_results (
    session_id varchar(32) PRIMARY KEY REFERENCES engine_items(id) ON DELETE CASCADE,
    student_name varchar(160),
    training_id varchar(40),
    task_id varchar(32),
    status varchar(32) NOT NULL,
    submitted_at timestamptz,
    grade integer,
    percent integer,
    timed_out boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_results_student ON session_results(student_name, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_results_training ON session_results(training_id, updated_at DESC) WHERE training_id IS NOT NULL;
