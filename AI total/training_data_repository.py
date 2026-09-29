"""Database access for the training data layer: schema 2.3.0 and import writes.

Этап 3 переносит учебные данные из JSON-файлов (data/t-*.json, data/s-*.json,
data/curriculum/*.json) в таблицы, созданные Этапом 2.2 (catalog_repository,
версия 2.2.0). Данный модуль добавляет только таблицу соответствий строковых
имён legacy_name_map (версия 2.3.0) и предоставляет транзакционную перезапись
учебных таблиц + батч-вставки через Simple Query (quote_literal), как это
сделано в catalog_repository.replace_classifier.

The import strategy is "full rewrite inside one transaction": the source of
truth on this stage is still JSON files, so TRUNCATE + re-insert is idempotent.
Tables "user", reference tables and utility tables are never touched here.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import db_config
import db_connection
from db_connection import quote_literal as q

SCHEMA_VERSION = '2.3.0'

# -------------------------------------------------------------------- DDL
# Only the new legacy-name mapping table belongs to this layer. Every other
# educational table already exists (created by catalog_repository, 2.2.0).

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS legacy_name_map (
        id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name       text NOT NULL UNIQUE,
        user_id    bigint NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        kind       text NOT NULL DEFAULT 'student'
                   CHECK (kind IN ('student', 'teacher')),
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_legacy_name_map_user ON legacy_name_map(user_id)',
]

# All educational tables that the importer owns. The "user" table, reference
# tables (service, classifier_*, geo_*) and utility tables (ai_generation_log,
# insight_report) are deliberately excluded.
TRAINING_TABLES = [
    'teacher_decision_field', 'teacher_decision',
    'ai_assessment_field', 'ai_assessment', 'machine_assessment',
    'session_reveal', 'session_card_edit', 'session_hint', 'session_turn',
    '"session"',
    'training_service_action', 'training_card', 'training_participant',
    'training_scenario', 'training',
    'scenario_task', 'scenario', 'material',
    'task_incident_source', 'task_dds', 'task',
    'legacy_name_map',
]

# Column orders used by the batch inserts. Order matters: it must match the
# tuples produced by training_data_service.build_rowsets().
TASK_COLUMNS = ('id', 'title', 'status', 'workflow', 'level', 'format',
                'opening', 'persona', 'fields', 'field_labels', 'source',
                'identity_hash', 'approved_by_id', 'approved_at',
                'created_at', 'updated_at')
TASK_DDS_COLUMNS = ('task_id', 'incoming_card', 'verification_notes', 'faults',
                    'service_name', 'service_role', 'service_knowledge', 'actions')
TASK_INCIDENT_COLUMNS = ('task_id', 'content', 'reference', 'caller_scenario', 'opening')

SCENARIO_COLUMNS = ('id', 'title', 'description', 'status', 'created_by_id',
                    'approved_by_id', 'approved_at', 'created_at', 'updated_at')
SCENARIO_TASK_COLUMNS = ('scenario_id', 'task_id', 'difficulty')

TRAINING_COLUMNS = ('id', 'title', 'description', 'status', 'mode', 'seconds',
                    'difficulty', 'teacher_id', 'group_name', 'created_at',
                    'started_at', 'completed_at', 'updated_at')
TRAINING_SCENARIO_COLUMNS = ('training_id', 'scenario_id')
TRAINING_PARTICIPANT_COLUMNS = ('training_id', 'user_id', 'role', 'service_code')
TRAINING_CARD_COLUMNS = ('id', 'training_id', 'task_id', 'operator_session_id',
                         'status', 'card_snapshot', 'services', 'submitted_at',
                         'dds_by_id', 'routed_at')
TRAINING_SERVICE_ACTION_COLUMNS = ('training_card_id', 'service_code', 'text', 'at')

MATERIAL_COLUMNS = ('id', 'title', 'url', 'description', 'teacher_id', 'created_at')

SESSION_COLUMNS = ('id', 'task_id', 'task_snapshot', 'reference_hash',
                   'student_id', 'status', 'effective_level', 'card',
                   'training_meta', 'callback_disclosed', 'connection',
                   'call_attempts', 'next_channel', 'timed_out', 'forced_finish',
                   'teacher_note', 'teacher_note_by_id', 'teacher_note_at',
                   'created_at', 'activated_at', 'submitted_at', 'updated_at')
SESSION_TURN_COLUMNS = ('session_id', 'turn_no', 'role', 'text', 'source',
                        'event', 'delivered', 'at')
SESSION_HINT_COLUMNS = ('session_id', 'text', 'at')
SESSION_CARD_EDIT_COLUMNS = ('session_id', 'field', 'before', 'after', 'at')
SESSION_REVEAL_COLUMNS = ('session_id', 'field', 'label', 'value', 'number', 'at')
MACHINE_ASSESSMENT_COLUMNS = ('session_id', 'percent', 'compared', 'method',
                              'fields', 'at')
AI_ASSESSMENT_COLUMNS = ('session_id', 'summary', 'percent', 'reference_hash',
                         'status', 'created_at')
AI_ASSESSMENT_FIELD_COLUMNS = ('assessment_id', 'field', 'verdict', 'comment',
                               'clarification', 'citation_warning', 'evidence')
TEACHER_DECISION_COLUMNS = ('session_id', 'teacher_id', 'grade', 'percent',
                            'conclusion', 'created_at')
TEACHER_DECISION_FIELD_COLUMNS = ('decision_id', 'field', 'decision', 'comment')
LEGACY_NAME_MAP_COLUMNS = ('name', 'user_id', 'kind')

_ALL_COLUMN_LISTS = (TASK_COLUMNS, TASK_DDS_COLUMNS, TASK_INCIDENT_COLUMNS,
                     SCENARIO_COLUMNS, SCENARIO_TASK_COLUMNS,
                     TRAINING_COLUMNS, TRAINING_SCENARIO_COLUMNS,
                     TRAINING_PARTICIPANT_COLUMNS, TRAINING_CARD_COLUMNS,
                     TRAINING_SERVICE_ACTION_COLUMNS, MATERIAL_COLUMNS,
                     SESSION_COLUMNS, SESSION_TURN_COLUMNS, SESSION_HINT_COLUMNS,
                     SESSION_CARD_EDIT_COLUMNS, SESSION_REVEAL_COLUMNS,
                     MACHINE_ASSESSMENT_COLUMNS, AI_ASSESSMENT_COLUMNS,
                     AI_ASSESSMENT_FIELD_COLUMNS, TEACHER_DECISION_COLUMNS,
                     TEACHER_DECISION_FIELD_COLUMNS, LEGACY_NAME_MAP_COLUMNS)


def sql_value(value) -> str:
    """Convert a Python value into a safely quoted SQL literal.

    None -> NULL, bool -> TRUE/FALSE, dict/list -> JSONB literal, numbers stay
    unquoted, strings go through quote_literal().
    """
    if value is None:
        return 'NULL'
    if value is True or value is False:
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (dict, list)):
        return q(json.dumps(value, ensure_ascii=False))
    return q(value)


class TrainingDataRepository:
    """Schema initializer (2.3.0) and import-oriented writes over DB."""

    def __init__(self, config: Optional[Dict[str, object]] = None):
        self._config = config or db_config.get_db_config()

    def _connect(self) -> db_connection.PostgresConnection:
        return db_connection.connect_from_config(self._config)

    # ----------------------------------------------------------------- schema

    def ensure_schema(self) -> None:
        """Create the legacy_name_map table and record version 2.3.0."""
        with self._connect() as connection:
            with connection.transaction():
                for statement in SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute(
                    'INSERT INTO schema_migration(version) VALUES (' + q(SCHEMA_VERSION)
                    + ') ON CONFLICT (version) DO NOTHING')

    def migration_version(self) -> Optional[str]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT version FROM schema_migration WHERE version = ' + q(SCHEMA_VERSION))
        return row[0] if row else None

    # ----------------------------------------------------------------- import

    @staticmethod
    def insert_many(connection, table: str, columns, rows, chunk: int = 200) -> int:
        """Insert rows (iterable of tuples) in batches. Returns inserted count."""
        if not rows:
            return 0
        total = 0
        col_sql = ', '.join(columns)
        for start in range(0, len(rows), chunk):
            batch = rows[start:start + chunk]
            values = ', '.join(
                '(' + ', '.join(sql_value(v) for v in row) + ')' for row in batch)
            connection.execute(
                'INSERT INTO ' + table + '(' + col_sql + ') VALUES ' + values)
            total += max(0, connection.rowcount)
        return total

    @staticmethod
    def insert_one_returning(connection, table: str, columns, row) -> int:
        """Insert a single row and return its identity/primary key."""
        col_sql = ', '.join(columns)
        values = ', '.join(sql_value(v) for v in row)
        rows = connection.execute(
            'INSERT INTO ' + table + '(' + col_sql + ') VALUES (' + values
            + ') RETURNING id')
        return int(rows[0][0]) if rows else 0

    def truncate_all(self, connection) -> None:
        """Empty every educational table inside the caller's transaction."""
        connection.execute('TRUNCATE ' + ', '.join(TRAINING_TABLES)
                           + ' RESTART IDENTITY CASCADE')

    # ------------------------------------------------------------------ users

    @staticmethod
    def find_user_by_display_name(connection, name: str) -> Optional[dict]:
        row = connection.fetchone(
            'SELECT id, login, password_hash, full_name, display_name, role,'
            ' is_active FROM "user" WHERE lower(btrim(display_name)) = '
            + q(str(name).strip().lower()))
        if row is None:
            return None
        return {'id': row[0], 'login': row[1], 'password_hash': row[2],
                'full_name': row[3], 'display_name': row[4], 'role': row[5],
                'is_active': str(row[6]).strip().lower() in ('t', 'true', '1')}

    @staticmethod
    def user_by_login(connection, login: str) -> Optional[int]:
        row = connection.fetchone(
            'SELECT id FROM "user" WHERE login = ' + q(login))
        return int(row[0]) if row else None

    @staticmethod
    def create_user(connection, login: str, password_hash: str, full_name: str,
                    role: str, display_name: Optional[str]) -> int:
        rows = connection.execute(
            'INSERT INTO "user"(login, password_hash, full_name, role, display_name)'
            ' VALUES (' + q(login) + ', ' + q(password_hash) + ', ' + q(full_name)
            + ', ' + q(role) + ', ' + q(display_name) + ') RETURNING id')
        return int(rows[0][0])

    @staticmethod
    def promote_user_to_teacher(connection, user_id: int) -> None:
        connection.execute(
            'UPDATE "user" SET role = ' + q('teacher') + ', updated_at = now()'
            ' WHERE id = ' + q(int(user_id)))

    @staticmethod
    def insert_legacy_names(connection, rows) -> int:
        """Insert (name, user_id, kind) rows; one row per unique name."""
        return TrainingDataRepository.insert_many(
            connection, 'legacy_name_map', LEGACY_NAME_MAP_COLUMNS, rows)

    # ---------------------------------------------------------------- checks

    def counts(self) -> dict:
        """Row counts of every educational table (used by --check/--self-test)."""
        result = {}
        with self._connect() as connection:
            for table in TRAINING_TABLES:
                row = connection.fetchone('SELECT count(*) FROM ' + table)
                result[table.strip('"')] = int(row[0]) if row else 0
        return result

    def integrity_issues(self) -> List[str]:
        """Return a list of referential or ordering problems, empty if healthy."""
        issues: List[str] = []
        with self._connect() as connection:
            for label, table, ref, target in (
                ('session→task', '"session"', 'task_id', 'task'),
                ('training_card→task', 'training_card', 'task_id', 'task'),
                ('training_card→training', 'training_card', 'training_id', 'training'),
                ('scenario_task→scenario', 'scenario_task', 'scenario_id', 'scenario'),
                ('scenario_task→task', 'scenario_task', 'task_id', 'task'),
            ):
                row = connection.fetchone(
                    'SELECT count(*) FROM ' + table + ' x LEFT JOIN ' + target
                    + ' t ON t.id = x.' + ref + ' WHERE t.id IS NULL')
                count = int(row[0]) if row else 0
                if count:
                    issues.append(f'{label}: {count} битых ссылок')
            # Sessions whose turns do not start from 1 or have gaps.
            row = connection.fetchone(
                'SELECT count(*) FROM ('
                ' SELECT session_id, turn_no,'
                ' rank() OVER (PARTITION BY session_id ORDER BY turn_no) AS r'
                ' FROM session_turn) x WHERE x.turn_no <> x.r')
            count = int(row[0]) if row else 0
            if count:
                issues.append(f'session_turn: {count} реплик с нарушенной нумерацией')
        return issues