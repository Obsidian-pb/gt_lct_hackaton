"""Row-level CRUD for the storage adapter (Этап 5: переключение репозитория).

Direct PostgreSQL access via db_connection (Simple Query protocol), mirroring
the auth/catalog/training-data repository patterns. Every public method opens
its own connection; multi-table writes run inside one transaction. Documents
(the Engine JSON format) are converted to/from rows by storage_documents.py.

Schema version 2.5.0 scopes cached insight reports to their owner and group,
while retaining the workshop-card content snapshot introduced in version 2.4.0.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable, Dict, List, Optional

import db_config
import db_connection
from db_connection import quote_literal as q

import storage_documents as docs
from training_data_repository import TrainingDataRepository

SCHEMA_VERSION = '2.5.0'

SCHEMA_STATEMENTS = [
    "CREATE TABLE IF NOT EXISTS insight_report ("
    "id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, group_name text, "
    "period text, report jsonb, created_at timestamptz NOT NULL DEFAULT now())",
    'ALTER TABLE insight_report ADD COLUMN IF NOT EXISTS source_updated_at timestamptz',
    'ALTER TABLE insight_report ADD COLUMN IF NOT EXISTS owner_id bigint',
    'DELETE FROM insight_report older USING insight_report newer'
    ' WHERE COALESCE(older.owner_id, 0) = COALESCE(newer.owner_id, 0)'
    " AND COALESCE(older.group_name, '') = COALESCE(newer.group_name, '')"
    ' AND older.period = newer.period AND older.id < newer.id',
    'DROP INDEX IF EXISTS idx_insight_report_group_period',
    'CREATE UNIQUE INDEX idx_insight_report_group_period'
    " ON insight_report (COALESCE(owner_id, 0), COALESCE(group_name, ''), period)",
    'CREATE INDEX IF NOT EXISTS idx_insight_report_created_at'
    ' ON insight_report(created_at)',
    # Exact browser content snapshot for master-workshop round trips.
    'ALTER TABLE workshop_card ADD COLUMN IF NOT EXISTS content jsonb',
    # Browser-side card UUID kept as an additional unique handle.
    'ALTER TABLE workshop_card ADD COLUMN IF NOT EXISTS uid text',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_workshop_card_uid ON workshop_card(uid)',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_workshop_card_number ON workshop_card(number)',
]

# ------------------------------------------------------------------ SQL utils


def sql_value(value) -> str:
    """Convert a Python value into a safely quoted SQL literal (dict/list = JSONB)."""
    if value is None:
        return 'NULL'
    if value is True or value is False:
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (dict, list)):
        return q(json.dumps(value, ensure_ascii=False))
    return q(value)


def _execute_params(connection, sql: str, params):
    execute_params = getattr(connection, 'execute_params', None)
    if callable(execute_params):
        return execute_params(sql, params)
    for index, value in enumerate(params, 1):
        sql = sql.replace(f'${index}', sql_value(value), 1)
    return connection.execute(sql)


def upsert_row(connection, table: str, columns, row, pk: str = 'id') -> None:
    """INSERT ... ON CONFLICT (pk) DO UPDATE, idempotent by natural key."""
    col_sql = ', '.join(columns)
    values = ', '.join(sql_value(v) for v in row)
    sets = ', '.join(f'{c} = EXCLUDED.{c}' for c in columns if c != pk)
    connection.execute(
        f'INSERT INTO {table}({col_sql}) VALUES ({values})'
        f' ON CONFLICT ({pk}) DO UPDATE SET {sets}')


def delete_where(connection, table: str, column: str, value) -> None:
    connection.execute(
        f'DELETE FROM {table} WHERE {column} = {sql_value(value)}')


def insert_one_returning(connection, table: str, columns, row) -> int:
    col_sql = ', '.join(columns)
    values = ', '.join(sql_value(v) for v in row)
    rows = connection.execute(
        f'INSERT INTO {table}({col_sql}) VALUES ({values}) RETURNING id')
    return int(rows[0][0]) if rows else 0


def row_dicts(rows, columns) -> List[dict]:
    """Zip wire-protocol row tuples with their column names."""
    return [dict(zip(columns, row)) for row in (rows or [])]


def first_row(rows, columns) -> Optional[dict]:
    result = row_dicts(rows, columns)
    return result[0] if result else None


# ------------------------------------------------------- column definitions
# Orders must match storage_documents converters and the importer.

TASK_COLUMNS = ('id', 'title', 'status', 'workflow', 'level', 'format',
                'opening', 'persona', 'fields', 'field_labels', 'source',
                'identity_hash', 'approved_by_id', 'approved_at',
                'created_at', 'updated_at')
TASK_DDS_COLUMNS = ('task_id', 'incoming_card', 'verification_notes', 'faults',
                    'service_name', 'service_role', 'service_knowledge', 'actions')
TASK_INCIDENT_COLUMNS = ('task_id', 'content', 'reference', 'caller_scenario', 'opening')

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

WORKSHOP_CARD_COLUMNS = ('id', 'number', 'uid', 'status', 'title', 'report',
                         'fields', 'class_ids', 'services', 'main_service',
                         'flags', 'provenance', 'revision', 'created_by_id',
                         'created_at', 'updated_at', 'caller_scenario', 'opening',
                         'geocoding', 'service_selection', 'content')
WORKSHOP_REFERENCE_COLUMNS = ('card_id', 'version', 'source_content', 'answer',
                              'model', 'prompt_version', 'created_at',
                              'edited_at', 'checked_at')
WORKSHOP_VERSION_COLUMNS = ('card_id', 'snapshot', 'review', 'action',
                            'created_at', 'author_id')
WORKSHOP_EVENT_COLUMNS = ('card_id', 'at', 'action', 'text', 'payload')
WORKSHOP_DIALOGUE_COLUMNS = ('card_id', 'turns', 'callback_disclosed')


class StorageRepository:
    """Document-oriented persistence over the educational + workshop tables."""

    def __init__(self, config: Optional[Dict[str, object]] = None):
        self._config = config or db_config.get_db_config()

    def _connect(self) -> db_connection.PostgresConnection:
        return db_connection.connection_from_config(self._config)

    # ----------------------------------------------------------------- schema

    def ensure_schema(self) -> None:
        """Apply schema statements and record the current migration version."""
        with self._connect() as connection:
            with connection.transaction():
                for statement in SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute(
                    'INSERT INTO schema_migration(version) VALUES ('
                    + q(SCHEMA_VERSION) + ') ON CONFLICT (version) DO NOTHING')

    def migration_version(self) -> Optional[str]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT version FROM schema_migration WHERE version = '
                + q(SCHEMA_VERSION))
        return row[0] if row else None

    # ------------------------------------------------------------------ users

    @staticmethod
    def _find_legacy_user(connection, name: str) -> Optional[int]:
        row = _execute_params(connection,
                              'SELECT user_id FROM legacy_name_map WHERE name = $1',
                              (name,))
        return int(row[0]) if row else None

    @staticmethod
    def _insert_legacy_name(connection, name: str, user_id: int, kind: str) -> None:
        connection.execute(
            'INSERT INTO legacy_name_map(name, user_id, kind) VALUES ('
            + q(name) + ', ' + q(int(user_id)) + ', ' + q(kind)
            + ') ON CONFLICT (name) DO NOTHING')

    def _resolve_name(self, connection, name, kind: str) -> Optional[int]:
        """Resolve legacy identity names without creating new accounts."""
        if name is None:
            return None
        key = str(name).strip()
        if not key:
            return None
        rows = _execute_params(
            connection,
            'SELECT id FROM "user" WHERE display_name = $1 OR login = $2'
            ' OR full_name = $3 ORDER BY CASE WHEN display_name = $1 THEN 0'
            ' WHEN login = $2 THEN 1 ELSE 2 END LIMIT 2',
            (key, key, key))
        if len(rows) > 1:
            raise ValueError('Имя неоднозначно; выберите уникальный логин пользователя.')
        existing = self._find_legacy_user(connection, key)
        if rows and existing is not None and existing != int(rows[0][0]):
            raise ValueError('Имя неоднозначно; выберите уникальный логин пользователя.')
        return int(rows[0][0]) if rows else existing

    def _name_of(self, connection) -> Callable:
        cache: Dict[int, Optional[str]] = {}

        def name_of(user_id) -> Optional[str]:
            if user_id is None:
                return None
            uid = int(user_id)
            if uid not in cache:
                row = connection.fetchone(
                    'SELECT display_name, full_name, login FROM "user"'
                    ' WHERE id = ' + q(uid))
                cache[uid] = (row[0] or row[1] or row[2]) if row else None
            return cache[uid]

        return name_of

    def _resolver(self, connection) -> Callable:
        def resolve(name, kind: str) -> Optional[int]:
            return self._resolve_name(connection, name, kind)

        return resolve

    def resolve_student(self, name: str) -> int:
        with self._connect() as connection:
            return self._resolve_student_in_connection(connection, name)

    def resolve_students(self, names: List[str]) -> List[int]:
        with self._connect() as connection:
            return [self._resolve_student_in_connection(connection, name) for name in names]

    @staticmethod
    def _resolve_student_in_connection(connection, name: str) -> int:
        rows = _execute_params(connection,
            'SELECT id FROM "user" WHERE (login = $1 OR display_name = $2'
            ' OR full_name = $3) AND role = $4 AND is_active = TRUE LIMIT 2',
            (name, name, name, 'student'))
        if len(rows) != 1:
            raise ValueError('Укажите уникальный логин действующего обучающегося.')
        return int(rows[0][0])

    # ------------------------------------------------------------------ tasks

    def upsert_task(self, doc: dict) -> None:
        with self._connect() as connection:
            with connection.transaction():
                rows = docs.task_to_rows(doc, self._resolver(connection))
                upsert_row(connection, 'task', TASK_COLUMNS, rows['task'])
                delete_where(connection, 'task_dds', 'task_id', doc['id'])
                if rows['task_dds'] is not None:
                    upsert_row(connection, 'task_dds', TASK_DDS_COLUMNS,
                               rows['task_dds'], pk='task_id')
                delete_where(connection, 'task_incident_source', 'task_id', doc['id'])
                if rows['task_incident'] is not None:
                    upsert_row(connection, 'task_incident_source',
                               TASK_INCIDENT_COLUMNS, rows['task_incident'],
                               pk='task_id')

    def _ensure_task_from_snapshot(self, connection, snapshot: dict) -> None:
        """Make sure the session FK target exists (upsert from the frozen task)."""
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('id'), str):
            raise ValueError('Сессия не содержит корректного снимка задания.')
        row = connection.fetchone(
            'SELECT id FROM task WHERE id = ' + q(snapshot['id']))
        if row is not None:
            return
        rows = docs.task_to_rows(snapshot, self._resolver(connection))
        upsert_row(connection, 'task', TASK_COLUMNS, rows['task'])
        if rows['task_dds'] is not None:
            upsert_row(connection, 'task_dds', TASK_DDS_COLUMNS,
                       rows['task_dds'], pk='task_id')
        if rows['task_incident'] is not None:
            upsert_row(connection, 'task_incident_source', TASK_INCIDENT_COLUMNS,
                       rows['task_incident'], pk='task_id')

    def _task_extensions(self, connection, identifiers) -> tuple:
        """Bulk-fetch task_dds and task_incident_source for a set of task ids."""
        if not identifiers:
            return {}, {}
        ids = ', '.join(q(value) for value in identifiers)
        dds = row_dicts(connection.execute(
            'SELECT task_id, incoming_card, verification_notes, faults,'
            ' service_name, service_role, service_knowledge, actions'
            ' FROM task_dds WHERE task_id IN (' + ids + ')'),
            ('task_id', 'incoming_card', 'verification_notes', 'faults',
             'service_name', 'service_role', 'service_knowledge', 'actions'))
        inc = row_dicts(connection.execute(
            'SELECT task_id, content, reference, caller_scenario, opening'
            ' FROM task_incident_source WHERE task_id IN (' + ids + ')'),
            ('task_id', 'content', 'reference', 'caller_scenario', 'opening'))
        return ({item['task_id']: item for item in dds},
                {item['task_id']: item for item in inc})

    def load_task(self, identifier: str) -> dict:
        with self._connect() as connection:
            row = first_row(connection.execute(
                'SELECT ' + ', '.join(TASK_COLUMNS) + ' FROM task WHERE id = '
                + q(identifier)), TASK_COLUMNS)
            if row is None:
                raise FileNotFoundError(identifier)
            dds_map, inc_map = self._task_extensions(connection, [identifier])
            return docs.task_from_row(
                row, dds_map.get(identifier), inc_map.get(identifier),
                self._name_of(connection))

    def list_tasks(self, owner: Optional[int] = None,
                   teacher: Optional[int] = None) -> List[dict]:
        with self._connect() as connection:
            filters = []
            if owner is not None:
                filters.append('approved_by_id = ' + q(int(owner)))
            if teacher is not None:
                teacher_id = q(int(teacher))
                filters.append('(approved_by_id = ' + teacher_id
                               + ' OR id IN (SELECT task_id FROM scenario_task'
                               + ' WHERE scenario_id IN (SELECT id FROM scenario'
                               + ' WHERE created_by_id = ' + teacher_id
                               + ' OR approved_by_id = ' + teacher_id + ')))')
            where = (' WHERE ' + ' AND '.join(filters)) if filters else ''
            rows = row_dicts(connection.execute(
                'SELECT ' + ', '.join(TASK_COLUMNS)
                + ' FROM task' + where + ' ORDER BY updated_at DESC, created_at DESC'),
                TASK_COLUMNS)
            if not rows:
                return []
            dds_map, inc_map = self._task_extensions(
                connection, [row['id'] for row in rows])
            name_of = self._name_of(connection)
            return [docs.task_from_row(row, dds_map.get(row['id']),
                                       inc_map.get(row['id']), name_of)
                    for row in rows]

    def exists_task(self, identifier: str) -> bool:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT 1 FROM task WHERE id = ' + q(identifier))
        return row is not None

    def task_belongs_to(self, identifier: str, user_id: int) -> bool:
        teacher_id = q(int(user_id))
        with self._connect() as connection:
            sql = ('SELECT 1 FROM task WHERE id = ' + q(identifier)
                   + ' AND (approved_by_id = ' + teacher_id
                   + ' OR id IN (SELECT st.task_id FROM scenario_task st'
                   + ' JOIN scenario sc ON sc.id = st.scenario_id'
                   + ' WHERE sc.created_by_id = ' + teacher_id
                   + ' OR sc.approved_by_id = ' + teacher_id + '))')
            row = connection.fetchone(sql)
        return row is not None

    def session_belongs_to_teacher(self, identifier: str, user_id: int) -> bool:
        teacher_id = q(int(user_id))
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT 1 FROM "session" s WHERE s.id = ' + q(identifier)
                + ' AND (s.task_id IN (SELECT id FROM task WHERE approved_by_id = '
                + teacher_id + ') OR s.id IN (SELECT tc.operator_session_id'
                ' FROM training_card tc JOIN training tr ON tr.id = tc.training_id'
                ' WHERE tr.teacher_id = ' + teacher_id + ') OR s.student_id IN ('
                'SELECT gm.user_id FROM group_member gm JOIN student_group sg'
                ' ON sg.id = gm.group_id WHERE sg.teacher_id = ' + teacher_id + '))')
        return row is not None

    def session_belongs_to_task_owner(self, identifier: str, task_id: str,
                                      user_id: int) -> bool:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT 1 FROM "session" WHERE id = ' + q(identifier)
                + ' AND task_id = ' + q(task_id)
                + ' AND task_id IN (SELECT id FROM task WHERE approved_by_id = '
                + q(int(user_id)) + ')')
        return row is not None

    # ---------------------------------------------------------------- sessions

    def upsert_session(self, doc: dict) -> None:
        with self._connect() as connection:
            with connection.transaction():
                parsed = docs.session_to_rows(doc, self._resolver(connection))
                self._ensure_task_from_snapshot(connection,
                                                (doc.get('task') or {}))
                upsert_row(connection, '"session"', SESSION_COLUMNS,
                           parsed['session'])
                session_id = doc['id']
                for table, rows in (
                        ('session_turn', parsed['turns']),
                        ('session_hint', parsed['hints']),
                        ('session_card_edit', parsed['edits']),
                        ('session_reveal', parsed['reveals'])):
                    delete_where(connection, table, 'session_id', session_id)
                    TrainingDataRepository.insert_many(
                        connection, table,
                        {'session_turn': SESSION_TURN_COLUMNS,
                         'session_hint': SESSION_HINT_COLUMNS,
                         'session_card_edit': SESSION_CARD_EDIT_COLUMNS,
                         'session_reveal': SESSION_REVEAL_COLUMNS}[table],
                        rows)
                delete_where(connection, 'machine_assessment', 'session_id', session_id)
                if parsed['machine'] is not None:
                    upsert_row(connection, 'machine_assessment',
                               MACHINE_ASSESSMENT_COLUMNS, parsed['machine'],
                               pk='session_id')
                connection.execute(
                    'DELETE FROM ai_assessment_field WHERE assessment_id IN'
                    ' (SELECT id FROM ai_assessment WHERE session_id = '
                    + q(session_id) + ')')
                connection.execute(
                    'DELETE FROM ai_assessment WHERE session_id = '
                    + q(session_id))
                if parsed['assessment'] is not None:
                    assessment_id = insert_one_returning(
                        connection, 'ai_assessment', AI_ASSESSMENT_COLUMNS,
                        parsed['assessment']['row'])
                    field_rows = [(assessment_id,) + f
                                  for f in parsed['assessment']['fields']]
                    TrainingDataRepository.insert_many(
                        connection, 'ai_assessment_field',
                        AI_ASSESSMENT_FIELD_COLUMNS, field_rows)
                connection.execute(
                    'DELETE FROM teacher_decision_field WHERE decision_id IN'
                    ' (SELECT id FROM teacher_decision WHERE session_id = '
                    + q(session_id) + ')')
                connection.execute(
                    'DELETE FROM teacher_decision WHERE session_id = '
                    + q(session_id))
                connection.execute(
                    'DELETE FROM teacher_decision_field WHERE decision_id IN'
                    ' (SELECT id FROM teacher_decision WHERE session_id = '
                    + q(session_id) + ')')
                connection.execute(
                    'DELETE FROM teacher_decision WHERE session_id = '
                    + q(session_id))
                if parsed['decision'] is not None:
                    decision_id = insert_one_returning(
                        connection, 'teacher_decision', TEACHER_DECISION_COLUMNS,
                        parsed['decision']['row'])
                    field_rows = [(decision_id,) + f
                                  for f in parsed['decision']['fields']]
                    TrainingDataRepository.insert_many(
                        connection, 'teacher_decision_field',
                        TEACHER_DECISION_FIELD_COLUMNS, field_rows)

    def _session_children(self, connection, session_id: str) -> dict:
        turns = row_dicts(connection.execute(
            'SELECT session_id, turn_no, role, text, source, event, delivered,'
            ' at FROM session_turn WHERE session_id = ' + q(session_id)
            + ' ORDER BY turn_no'), SESSION_TURN_COLUMNS)
        hints = row_dicts(connection.execute(
            'SELECT session_id, text, at FROM session_hint WHERE session_id = '
            + q(session_id) + ' ORDER BY id'), SESSION_HINT_COLUMNS)
        edits = row_dicts(connection.execute(
            'SELECT session_id, field, before, after, at FROM session_card_edit'
            ' WHERE session_id = ' + q(session_id) + ' ORDER BY id'),
            SESSION_CARD_EDIT_COLUMNS)
        reveals = row_dicts(connection.execute(
            'SELECT session_id, field, label, value, number, at FROM'
            ' session_reveal WHERE session_id = ' + q(session_id)
            + ' ORDER BY id'), SESSION_REVEAL_COLUMNS)
        machine = first_row(connection.execute(
            'SELECT session_id, percent, compared, method, fields, at FROM'
            ' machine_assessment WHERE session_id = ' + q(session_id)),
            MACHINE_ASSESSMENT_COLUMNS)
        assessment = first_row(connection.execute(
            'SELECT session_id, summary, percent, reference_hash, status,'
            ' created_at FROM ai_assessment WHERE session_id = '
            + q(session_id)), AI_ASSESSMENT_COLUMNS)
        assessment_fields = []
        if assessment is not None:
            assessment_fields = row_dicts(connection.execute(
                'SELECT f.assessment_id, f.field, f.verdict, f.comment,'
                ' f.clarification, f.citation_warning, f.evidence FROM'
                ' ai_assessment_field f JOIN ai_assessment a ON a.id ='
                ' f.assessment_id WHERE a.session_id = ' + q(session_id)),
                AI_ASSESSMENT_FIELD_COLUMNS)
        decision = first_row(connection.execute(
            'SELECT session_id, teacher_id, grade, percent, conclusion,'
            ' created_at FROM teacher_decision WHERE session_id = '
            + q(session_id)), TEACHER_DECISION_COLUMNS)
        decision_fields = []
        if decision is not None:
            decision_fields = row_dicts(connection.execute(
                'SELECT f.decision_id, f.field, f.decision, f.comment FROM'
                ' teacher_decision_field f JOIN teacher_decision d ON d.id ='
                ' f.decision_id WHERE d.session_id = ' + q(session_id)),
                TEACHER_DECISION_FIELD_COLUMNS)
        return {'turns': turns, 'hints': hints, 'edits': edits,
                'reveals': reveals, 'machine': machine,
                'assessment': assessment, 'assessment_fields': assessment_fields,
                'decision': decision, 'decision_fields': decision_fields}

    def load_session(self, identifier: str) -> dict:
        with self._connect() as connection:
            row = first_row(connection.execute(
                'SELECT ' + ', '.join(SESSION_COLUMNS) + ' FROM "session"'
                ' WHERE id = ' + q(identifier)), SESSION_COLUMNS)
            if row is None:
                raise FileNotFoundError(identifier)
            children = self._session_children(connection, identifier)
            return docs.session_from_row(row, name_of=self._name_of(connection),
                                         **children)

    def session_belongs_to(self, identifier: str, user_id: int) -> bool:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT 1 FROM "session" WHERE id = ' + q(identifier)
                + ' AND student_id = ' + q(int(user_id)))
        return row is not None

    def list_sessions(self, owner: Optional[int] = None,
                      teacher: Optional[int] = None) -> List[dict]:
        with self._connect() as connection:
            filters = []
            if owner is not None:
                filters.append('student_id = ' + q(int(owner)))
            if teacher is not None:
                teacher_id = q(int(teacher))
                filters.append('(task_id IN (SELECT id FROM task WHERE approved_by_id = '
                               + teacher_id + ') OR id IN (SELECT tc.operator_session_id'
                               ' FROM training_card tc JOIN training tr ON tr.id = tc.training_id'
                               ' WHERE tr.teacher_id = ' + teacher_id + ') OR student_id IN ('
                               'SELECT gm.user_id FROM group_member gm JOIN student_group sg'
                               ' ON sg.id = gm.group_id WHERE sg.teacher_id = ' + teacher_id + '))')
            where = (' WHERE ' + ' AND '.join(filters)) if filters else ''
            rows = row_dicts(connection.execute(
                'SELECT ' + ', '.join(SESSION_COLUMNS) + ' FROM "session"'
                + where + ' ORDER BY created_at DESC, id'), SESSION_COLUMNS)
            name_of = self._name_of(connection)
            result = []
            for row in rows:
                children = self._session_children(connection, row['id'])
                result.append(docs.session_from_row(
                    row, name_of=name_of, **children))
            return result

    def list_sessions_summary(self, teacher: Optional[int] = None) -> List[dict]:
        """Return teacher-dashboard rows without loading session/task documents.

        In particular, ``task_snapshot`` and ``card`` stay inside PostgreSQL:
        only their needed metadata (task fields and card counts) is projected.
        """
        filters = []
        if teacher is not None:
            teacher_id = q(int(teacher))
            filters.append(
                '(s.task_id IN (SELECT id FROM task WHERE approved_by_id = '
                + teacher_id + ') OR s.id IN (SELECT tc.operator_session_id'
                ' FROM training_card tc JOIN training tr ON tr.id = tc.training_id'
                ' WHERE tr.teacher_id = ' + teacher_id + ') OR s.student_id IN ('
                'SELECT gm.user_id FROM group_member gm JOIN student_group sg'
                ' ON sg.id = gm.group_id WHERE sg.teacher_id = ' + teacher_id + '))')
        where = (' WHERE ' + ' AND '.join(filters)) if filters else ''
        columns = (
            'id', 'student', 'title', 'task_id', 'status', 'level', 'workflow',
            'created_at', 'updated_at', 'duration_seconds', 'filled',
            'total_fields', 'grade', 'machine_percent', 'ai_percent',
            'final_percent', 'ai_remarks', 'training', 'comment',
            'category_class_ids')
        sql = (
            'SELECT s.id, COALESCE(u.display_name, u.full_name, u.login, \'\') AS student,'
            " COALESCE(s.task_snapshot->>'title', t.title) AS title, s.task_id, s.status,"
            " COALESCE(s.effective_level, s.task_snapshot->>'level', t.level) AS level,"
            " COALESCE(s.task_snapshot->>'workflow', t.workflow, 'caller') AS workflow,"
            ' s.created_at, s.updated_at,'
            " CASE WHEN s.status = 'queued' THEN 0 ELSE GREATEST(0,"
            ' FLOOR(EXTRACT(EPOCH FROM (COALESCE(s.submitted_at, now()) -'
            ' COALESCE(s.activated_at, s.created_at))))::int) END AS duration_seconds,'
            " (SELECT COUNT(*) FROM jsonb_each_text(CASE WHEN jsonb_typeof(s.card) = 'object'"
            " THEN s.card ELSE '{}'::jsonb END) AS card_field(key, value)"
            " WHERE btrim(card_field.value) <> '') AS filled,"
            " (SELECT COUNT(*) FROM jsonb_object_keys(CASE WHEN jsonb_typeof(s.card) = 'object'"
            " THEN s.card ELSE '{}'::jsonb END)) AS total_fields,"
            ' decision.grade, machine.percent AS machine_percent,'
            ' ai.percent AS ai_percent, decision.percent AS final_percent, ai.remarks AS ai_remarks,'
            ' s.training_meta AS training, COALESCE(s.teacher_note, \'\') AS comment,'
            " COALESCE(tis.content->'class_ids', s.task_snapshot->'incident_source'->'class_ids',"
            " '[]'::jsonb) AS category_class_ids"
            ' FROM "session" s JOIN "user" u ON u.id = s.student_id'
            ' LEFT JOIN task t ON t.id = s.task_id'
            ' LEFT JOIN task_incident_source tis ON tis.task_id = s.task_id'
            ' LEFT JOIN LATERAL (SELECT d.grade, d.percent FROM teacher_decision d'
            ' WHERE d.session_id = s.id ORDER BY d.created_at DESC, d.id DESC LIMIT 1) decision ON TRUE'
            ' LEFT JOIN LATERAL (SELECT m.percent FROM machine_assessment m'
            ' WHERE m.session_id = s.id ORDER BY m.at DESC, m.id DESC LIMIT 1) machine ON TRUE'
            ' LEFT JOIN LATERAL (SELECT a.percent,'
            ' (SELECT COUNT(*) FROM ai_assessment_field f WHERE f.assessment_id = a.id'
            " AND f.verdict IN ('partial', 'incorrect', 'missing')) AS remarks"
            ' FROM ai_assessment a WHERE a.session_id = s.id'
            ' ORDER BY a.created_at DESC, a.id DESC LIMIT 1) ai ON TRUE'
            + where + ' ORDER BY s.created_at DESC, s.id')
        with self._connect() as connection:
            rows = row_dicts(connection.execute(sql), columns)
        result = []
        for row in rows:
            row['created_at'] = docs.load_ts(row.get('created_at'))
            row['updated_at'] = docs.load_ts(row.get('updated_at'))
            row['duration_seconds'] = int(row.get('duration_seconds') or 0)
            row['filled'] = int(row.get('filled') or 0)
            row['total_fields'] = int(row.get('total_fields') or 0)
            row['category_class_ids'] = docs._list(row.get('category_class_ids'))
            row['training'] = docs._dict(row.get('training')) or None
            row['grade'] = int(row['grade']) if row.get('grade') is not None else None
            for key in ('machine_percent', 'ai_percent', 'final_percent', 'ai_remarks'):
                row[key] = int(row[key]) if row.get(key) is not None else None
            result.append(row)
        return result

    # -------------------------------------------------------------- scenarios

    def upsert_scenario(self, doc: dict) -> None:
        with self._connect() as connection:
            with connection.transaction():
                rows = docs.scenario_to_rows(doc, self._resolver(connection))
                upsert_row(connection, 'scenario', SCENARIO_COLUMNS, rows['scenario'])
                delete_where(connection, 'scenario_task', 'scenario_id', doc['id'])
                TrainingDataRepository.insert_many(
                    connection, 'scenario_task', SCENARIO_TASK_COLUMNS,
                    [(doc['id'], task_id, difficulty)
                     for task_id, difficulty in rows['tasks']])

    def scenario_belongs_to(self, identifier: str, user_id: int) -> bool:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT 1 FROM scenario WHERE id = ' + q(identifier)
                + ' AND (created_by_id = ' + q(int(user_id))
                + ' OR approved_by_id = ' + q(int(user_id)) + ')')
        return row is not None

    def training_belongs_to(self, identifier: str, user_id: int) -> bool:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT 1 FROM training WHERE id = ' + q(identifier)
                + ' AND teacher_id = ' + q(int(user_id)))
        return row is not None

    def load_scenario(self, identifier: str) -> dict:
        with self._connect() as connection:
            row = first_row(connection.execute(
                'SELECT ' + ', '.join(SCENARIO_COLUMNS) + ' FROM scenario'
                ' WHERE id = ' + q(identifier)), SCENARIO_COLUMNS)
            if row is None:
                raise FileNotFoundError(identifier)
            tasks = row_dicts(connection.execute(
                'SELECT scenario_id, task_id, difficulty FROM scenario_task'
                ' WHERE scenario_id = ' + q(identifier)
                + ' ORDER BY task_id'), SCENARIO_TASK_COLUMNS)
            return docs.scenario_from_row(row, tasks,
                                          self._name_of(connection))

    def list_scenarios(self, owner: Optional[int] = None) -> List[dict]:
        with self._connect() as connection:
            where = (' WHERE created_by_id = ' + q(int(owner))
                     + ' OR approved_by_id = ' + q(int(owner))) if owner is not None else ''
            rows = row_dicts(connection.execute(
                'SELECT ' + ', '.join(SCENARIO_COLUMNS) + ' FROM scenario'
                + where + ' ORDER BY created_at DESC, id'), SCENARIO_COLUMNS)
            name_of = self._name_of(connection)
            result = []
            for row in rows:
                tasks = row_dicts(connection.execute(
                    'SELECT scenario_id, task_id, difficulty FROM scenario_task'
                    ' WHERE scenario_id = ' + q(row['id']) + ' ORDER BY task_id'),
                    SCENARIO_TASK_COLUMNS)
                result.append(docs.scenario_from_row(row, tasks, name_of))
            return result

    def delete_scenario(self, identifier: str) -> None:
        with self._connect() as connection:
            with connection.transaction():
                connection.execute('DELETE FROM scenario WHERE id = ' + q(identifier))

    # -------------------------------------------------------------- trainings

    def upsert_training(self, doc: dict) -> None:
        with self._connect() as connection:
            with connection.transaction():
                rows = docs.training_to_rows(doc, self._resolver(connection))
                if any(row[1] is None for row in rows['participants']):
                    raise ValueError('Участник тренировки не найден среди пользователей.')
                upsert_row(connection, 'training', TRAINING_COLUMNS, rows['training'])
                training_id = doc['id']
                delete_where(connection, 'training_scenario', 'training_id', training_id)
                TrainingDataRepository.insert_many(
                    connection, 'training_scenario', TRAINING_SCENARIO_COLUMNS,
                    [(training_id, scenario_id)
                     for scenario_id in rows['scenarios']])
                delete_where(connection, 'training_participant', 'training_id', training_id)
                TrainingDataRepository.insert_many(
                    connection, 'training_participant', TRAINING_PARTICIPANT_COLUMNS,
                    rows['participants'])
                connection.execute(
                    'DELETE FROM training_service_action WHERE training_card_id IN'
                    ' (SELECT id FROM training_card WHERE training_id = '
                    + q(training_id) + ')')
                delete_where(connection, 'training_card', 'training_id', training_id)
                for card in rows['cards']:
                    upsert_row(connection, 'training_card', TRAINING_CARD_COLUMNS,
                               card['row'])
                    TrainingDataRepository.insert_many(
                        connection, 'training_service_action',
                        TRAINING_SERVICE_ACTION_COLUMNS, card['actions'])

    def _training_children(self, connection, identifier: str) -> dict:
        scenarios = row_dicts(connection.execute(
            'SELECT training_id, scenario_id FROM training_scenario'
            ' WHERE training_id = ' + q(identifier)),
            TRAINING_SCENARIO_COLUMNS)
        participants = row_dicts(connection.execute(
            'SELECT training_id, user_id, role, service_code FROM'
            ' training_participant WHERE training_id = ' + q(identifier)),
            TRAINING_PARTICIPANT_COLUMNS)
        cards = row_dicts(connection.execute(
            'SELECT ' + ', '.join(TRAINING_CARD_COLUMNS) + ' FROM training_card'
            ' WHERE training_id = ' + q(identifier) + ' ORDER BY id'),
            TRAINING_CARD_COLUMNS)
        actions = []
        if cards:
            ids = ', '.join(q(card['id']) for card in cards)
            actions = row_dicts(connection.execute(
                'SELECT training_card_id, service_code, text, at FROM'
                ' training_service_action WHERE training_card_id IN (' + ids
                + ') ORDER BY id'), TRAINING_SERVICE_ACTION_COLUMNS)
        return {'scenarios': scenarios, 'participants': participants,
                'cards': cards, 'actions': actions}

    def training_participant_belongs_to(self, identifier: str, user_id: int,
                                        role: str) -> bool:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT 1 FROM training_participant WHERE training_id = ' + q(identifier)
                + ' AND user_id = ' + q(int(user_id)) + ' AND role = ' + q(role))
        return row is not None

    def list_training_desks(self, user_id: int) -> List[dict]:
        with self._connect() as connection:
            rows = row_dicts(connection.execute(
                'SELECT ' + ', '.join('tr.' + column for column in TRAINING_COLUMNS)
                + ' FROM training tr JOIN training_participant tp ON tp.training_id = tr.id'
                + ' WHERE tp.user_id = ' + q(int(user_id))
                + ' ORDER BY tr.created_at DESC, tr.id'), TRAINING_COLUMNS)
            name_of = self._name_of(connection)
            return [docs.training_from_row(row, name_of=name_of,
                                            **self._training_children(connection, row['id']))
                    for row in rows]

    def load_training(self, identifier: str) -> dict:
        with self._connect() as connection:
            row = first_row(connection.execute(
                'SELECT ' + ', '.join(TRAINING_COLUMNS) + ' FROM training'
                ' WHERE id = ' + q(identifier)), TRAINING_COLUMNS)
            if row is None:
                raise FileNotFoundError(identifier)
            children = self._training_children(connection, identifier)
            return docs.training_from_row(row,
                                          name_of=self._name_of(connection),
                                          **children)

    def list_trainings(self, owner: Optional[int] = None) -> List[dict]:
        with self._connect() as connection:
            where = (' WHERE teacher_id = ' + q(int(owner))) if owner is not None else ''
            rows = row_dicts(connection.execute(
                'SELECT ' + ', '.join(TRAINING_COLUMNS) + ' FROM training'
                + where + ' ORDER BY created_at DESC, id'), TRAINING_COLUMNS)
            name_of = self._name_of(connection)
            result = []
            for row in rows:
                children = self._training_children(connection, row['id'])
                result.append(docs.training_from_row(
                    row, name_of=name_of, **children))
            return result

    def delete_training(self, identifier: str) -> None:
        with self._connect() as connection:
            with connection.transaction():
                connection.execute('DELETE FROM training WHERE id = ' + q(identifier))

    # -------------------------------------------------------------- materials

    def upsert_material(self, doc: dict) -> None:
        with self._connect() as connection:
            with connection.transaction():
                upsert_row(connection, 'material', MATERIAL_COLUMNS,
                           docs.material_to_rows(doc, self._resolver(connection)))

    def list_materials(self, owner: Optional[int] = None) -> List[dict]:
        with self._connect() as connection:
            where = (' WHERE teacher_id = ' + q(int(owner))) if owner is not None else ''
            rows = row_dicts(connection.execute(
                'SELECT ' + ', '.join(MATERIAL_COLUMNS) + ' FROM material'
                + where + ' ORDER BY created_at DESC, id'), MATERIAL_COLUMNS)
            name_of = self._name_of(connection)
            return [docs.material_from_row(row, name_of) for row in rows]

    # ---------------------------------------------------- integrity / counts

    # -------------------------------------------------------------- workshop

    @staticmethod
    def _workshop_number(content: dict) -> str:
        existing = str(content.get('number') or '').strip()
        if existing:
            return existing
        return 'К-' + uuid.uuid4().hex[:8].upper()

    @staticmethod
    def _workshop_uid(content: dict) -> str:
        existing = str(content.get('id') or '').strip()
        if existing and len(existing) <= 64:
            return existing
        return uuid.uuid4().hex

    @staticmethod
    def _merge_workshop_doc(row: dict) -> dict:
        """Merge a workshop_card row + children into the browser-style document."""
        content = docs._dict(row.get('content'))
        if not isinstance(content, dict):
            content = {}
        doc = dict(content)
        doc.setdefault('id', row.get('uid'))
        doc['number'] = row.get('number')
        doc['status'] = row.get('status')
        doc['revision'] = int(row.get('revision') or 0)
        doc['created_at'] = docs.load_ts(row.get('created_at'))
        doc['updated_at'] = docs.load_ts(row.get('updated_at'))
        return doc

    def _workshop_children(self, connection, card_id: int, doc: dict) -> None:
        """Rewrite journal/reference/dialogue rows from the browser document."""
        delete_where(connection, 'workshop_card_event', 'card_id', card_id)
        history = doc.get('history') if isinstance(doc.get('history'), list) else []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            payload = {key: entry[key] for key in entry
                       if key not in ('at', 'action', 'text')}
            connection.execute(
                'INSERT INTO workshop_card_event(card_id, at, action, text, payload)'
                ' VALUES (' + q(int(card_id)) + ', '
                + q(docs.load_ts(entry.get('at')) or docs._now())
                + ', ' + q(str(entry.get('action') or ''))
                + ', ' + q(str(entry.get('text') or ''))
                + ', ' + (q(json.dumps(payload, ensure_ascii=False)) if payload else 'NULL')
                + ')')
        delete_where(connection, 'workshop_card_reference', 'card_id', card_id)
        reference = doc.get('reference')
        if isinstance(reference, dict):
            source = reference.get('source_content')
            answer = reference.get('answer')
            connection.execute(
                'INSERT INTO workshop_card_reference(card_id, version, source_content,'
                ' answer, model, prompt_version, edited_at, checked_at) VALUES ('
                + q(int(card_id)) + ', 1, ' + sql_value(source) + ', '
                + sql_value(answer) + ', ' + sql_value(reference.get('model'))
                + ', ' + sql_value(reference.get('prompt_version')) + ', now(), now())')
        delete_where(connection, 'workshop_card_dialogue', 'card_id', card_id)
        dialogue = doc.get('caller_dialogue')
        if isinstance(dialogue, dict):
            connection.execute(
                'INSERT INTO workshop_card_dialogue(card_id, turns, callback_disclosed)'
                ' VALUES (' + q(int(card_id)) + ', ' + sql_value(dialogue.get('turns'))
                + ', ' + ('TRUE' if dialogue.get('callback_disclosed') else 'FALSE') + ')')

    def _workshop_upsert(self, connection, content: dict, author_id) -> str:
        """Insert or update a workshop card by number; returns the number."""
        number = self._workshop_number(content)
        uid = self._workshop_uid(content)
        fields = content.get('fields') if isinstance(content.get('fields'), dict) else {}
        class_ids = content.get('class_ids') if isinstance(content.get('class_ids'), list) else []
        services = content.get('services') if isinstance(content.get('services'), list) else []
        flags = content.get('flags') if isinstance(content.get('flags'), dict) else {}
        provenance = content.get('provenance')
        caller_scenario = content.get('caller_scenario')
        opening = content.get('training_opening') or content.get('opening')
        status = content.get('status')
        if status not in ('draft', 'approved'):
            status = 'draft'
        current = connection.fetchone(
            'SELECT id, revision FROM workshop_card WHERE number = ' + q(number))
        revision = (int(current[1]) if current else 0) + 1
        client_revision = content.get('revision')
        if isinstance(client_revision, int) and client_revision > revision:
            revision = client_revision
        # Raw Python values; sql_value() serializes each one exactly once.
        values = (
            number, uid, status,
            str(content.get('title') or ''), str(content.get('report') or ''),
            fields, class_ids, services,
            str(content.get('main_service') or ''), flags,
            provenance, revision, author_id, caller_scenario, opening,
            content.get('geocoding'), content.get('service_selection'), content,
        )
        columns = ('number', 'uid', 'status', 'title', 'report', 'fields',
                   'class_ids', 'services', 'main_service', 'flags',
                   'provenance', 'revision', 'created_by_id', 'caller_scenario',
                   'opening', 'geocoding', 'service_selection', 'content')
        if current is None:
            col_sql = ', '.join(columns)
            vals = ', '.join(sql_value(v) for v in values)
            rows = connection.execute(
                'INSERT INTO workshop_card(' + col_sql + ') VALUES (' + vals
                + ') RETURNING id')
            card_id = int(rows[0][0])
        else:
            card_id = int(current[0])
            upsert_row(connection, 'workshop_card', columns, values, pk='number')
        self._workshop_children(connection, card_id, content)
        return number

    def workshop_list(self) -> List[dict]:
        """Brief cards for the master-workshop journal (no heavy content)."""
        with self._connect() as connection:
            return row_dicts(connection.execute(
                'SELECT id, number, uid, status, title, revision, created_at,'
                ' updated_at FROM workshop_card ORDER BY updated_at DESC, id DESC'),
                ('id', 'number', 'uid', 'status', 'title', 'revision',
                 'created_at', 'updated_at'))

    def workshop_get(self, reference: str) -> dict:
        with self._connect() as connection:
            row = first_row(connection.execute(
                'SELECT id, number, uid, status, title, report, fields, class_ids,'
                ' services, main_service, flags, provenance, revision, created_by_id,'
                ' created_at, updated_at, caller_scenario, opening, geocoding,'
                ' service_selection, content FROM workshop_card'
                ' WHERE number = ' + q(reference) + ' OR uid = ' + q(reference)),
                WORKSHOP_CARD_COLUMNS)
            if row is None:
                raise FileNotFoundError(reference)
            doc = self._merge_workshop_doc(row)
            reference_row = first_row(connection.execute(
                'SELECT card_id, version, source_content, answer, model,'
                ' prompt_version, created_at, edited_at, checked_at FROM'
                ' workshop_card_reference WHERE card_id = ' + q(int(row['id']))
                + ' ORDER BY version DESC LIMIT 1'), WORKSHOP_REFERENCE_COLUMNS)
            if reference_row is not None:
                doc['reference'] = {
                    'source_content': docs._dict(reference_row.get('source_content')),
                    'answer': docs._dict(reference_row.get('answer'))}
            dialogue = first_row(connection.execute(
                'SELECT card_id, turns, callback_disclosed FROM'
                ' workshop_card_dialogue WHERE card_id = ' + q(int(row['id']))),
                WORKSHOP_DIALOGUE_COLUMNS)
            if dialogue is not None:
                doc['caller_dialogue'] = {
                    'turns': docs._list(dialogue.get('turns')),
                    'callback_disclosed': docs._bool(dialogue.get('callback_disclosed'))}
            events = row_dicts(connection.execute(
                'SELECT card_id, at, action, text, payload FROM workshop_card_event'
                ' WHERE card_id = ' + q(int(row['id'])) + ' ORDER BY id'),
                WORKSHOP_EVENT_COLUMNS)
            history = []
            for event in events:
                item = {'at': docs.load_ts(event.get('at')),
                        'action': event.get('action') or '',
                        'text': event.get('text') or ''}
                payload = event.get('payload')
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        payload = None
                if isinstance(payload, dict):
                    item.update(payload)
                history.append(item)
            doc['history'] = history
            return doc

    def workshop_create(self, content: dict, author_id) -> dict:
        with self._connect() as connection:
            with connection.transaction():
                number = self._workshop_upsert(connection, content, author_id)
                return self._read_workshop(connection, number)

    def workshop_update(self, reference: str, content: dict, author_id) -> dict:
        with self._connect() as connection:
            with connection.transaction():
                number = self._workshop_find_number(connection, reference)
                if number is None:
                    raise FileNotFoundError(reference)
                content['number'] = number
                self._workshop_upsert(connection, content, author_id)
                return self._read_workshop(connection, number)

    def workshop_approve(self, reference: str, review: dict, author_id) -> dict:
        with self._connect() as connection:
            with connection.transaction():
                number = self._workshop_find_number(connection, reference)
                if number is None:
                    raise FileNotFoundError(reference)
                row = first_row(connection.execute(
                    'SELECT id, content FROM workshop_card WHERE number = '
                    + q(number)), ('id', 'content'))
                doc = docs._dict(row.get('content'))
                doc['status'] = 'approved'
                doc['review'] = review
                doc['history'] = (doc.get('history') or []) + [
                    {'at': docs._now(), 'action': 'approved',
                     'text': 'Утверждено: ' + str((review or {}).get('teacher') or ''),
                     'review': dict(review or {}),
                     'content': dict(doc)}]
                self._workshop_upsert(connection, doc, author_id)
                connection.execute(
                    'INSERT INTO workshop_card_version(card_id, snapshot, review,'
                    ' action, created_at, author_id) VALUES (' + q(int(row['id']))
                    + ', ' + sql_value({'content': doc, 'reference': doc.get('reference')})
                    + ', ' + sql_value(review) + ', ' + q('approved')
                    + ', now(), ' + sql_value(author_id) + ')')
                return self._read_workshop(connection, number)

    def workshop_reopen(self, reference: str, author_id) -> dict:
        with self._connect() as connection:
            with connection.transaction():
                number = self._workshop_find_number(connection, reference)
                if number is None:
                    raise FileNotFoundError(reference)
                row = first_row(connection.execute(
                    'SELECT id, content FROM workshop_card WHERE number = '
                    + q(number)), ('id', 'content'))
                doc = docs._dict(row.get('content'))
                doc['status'] = 'draft'
                doc['review'] = None
                doc['history'] = (doc.get('history') or []) + [
                    {'at': docs._now(), 'action': 'reopened',
                     'text': 'Возвращена на доработку; предыдущее утверждение отменено'}]
                self._workshop_upsert(connection, doc, author_id)
                return self._read_workshop(connection, number)

    def workshop_delete(self, reference: str) -> bool:
        with self._connect() as connection:
            with connection.transaction():
                number = self._workshop_find_number(connection, reference)
                if number is None:
                    return False
                connection.execute('DELETE FROM workshop_card WHERE number = '
                                   + q(number))
                return True

    def workshop_import(self, cards: List[dict], author_id) -> int:
        """Upsert imported cards by number (project decision №7)."""
        imported = 0
        with self._connect() as connection:
            with connection.transaction():
                for card in cards:
                    if not isinstance(card, dict):
                        continue
                    self._workshop_upsert(connection, card, author_id)
                    imported += 1
        return imported

    @staticmethod
    def _workshop_find_number(connection, reference: str) -> Optional[str]:
        row = connection.fetchone(
            'SELECT number FROM workshop_card WHERE number = ' + q(reference)
            + ' OR uid = ' + q(reference))
        return row[0] if row else None

    def _read_workshop(self, connection, number: str) -> dict:
        row = first_row(connection.execute(
            'SELECT id, number, uid, status, title, report, fields, class_ids,'
            ' services, main_service, flags, provenance, revision, created_by_id,'
            ' created_at, updated_at, caller_scenario, opening, geocoding,'
            ' service_selection, content FROM workshop_card WHERE number = '
            + q(number)), WORKSHOP_CARD_COLUMNS)
        if row is None:
            raise FileNotFoundError(number)
        return self._merge_workshop_doc(row)

    # -------------------------------------------------------------- analytics

    def insight_source(self, group: Optional[str] = None,
                       owner: Optional[int] = None):
        """Return assessment freshness and anonymized error aggregates."""
        group_join = (' LEFT JOIN training tr ON tr.id = s.training_meta->>\'plan_id\''
                      if group or owner is not None else '')
        filters = ["s.status IN ('submitted', 'pending_teacher', 'reviewed')"]
        if group:
            filters.append('COALESCE(tr.group_name, s.training_meta->>\'group\') = '
                           + q(group))
        if owner is not None:
            teacher_id = q(int(owner))
            filters.append('(tr.teacher_id = ' + teacher_id
                           + ' OR s.task_id IN (SELECT id FROM task WHERE approved_by_id = '
                           + teacher_id + ') OR s.student_id IN ('
                           'SELECT gm.user_id FROM group_member gm JOIN student_group sg'
                           ' ON sg.id = gm.group_id WHERE sg.teacher_id = '
                           + teacher_id + '))')
        where = ' WHERE ' + ' AND '.join(filters)
        source_sql = (
            'WITH latest AS (SELECT DISTINCT ON (s.id) s.id, s.updated_at, '
            's.task_snapshot, s.task_id, aa.id AS assessment_id '
            'FROM "session" s JOIN ai_assessment aa ON aa.session_id = s.id'
            + group_join + where + ' ORDER BY s.id, aa.created_at DESC, aa.id DESC) '
            'SELECT COUNT(*), MAX(updated_at) FROM latest')
        count_sql = (
            'WITH latest AS (SELECT DISTINCT ON (s.id) s.id, s.task_snapshot, '
            's.task_id, aa.id AS assessment_id FROM "session" s '
            'JOIN ai_assessment aa ON aa.session_id = s.id'
            + group_join + where + ' ORDER BY s.id, aa.created_at DESC, aa.id DESC) '
            'SELECT COALESCE(l.task_snapshot->\'field_labels\'->>f.field, '
            't.field_labels->>f.field, f.field) AS label, COUNT(*) '
            'FROM latest l JOIN ai_assessment_field f '
            'ON f.assessment_id = l.assessment_id '
            'LEFT JOIN task t ON t.id = l.task_id '
            "WHERE f.verdict IN ('incorrect', 'missing', 'partial') "
            'GROUP BY 1')
        with self._connect() as connection:
            source = connection.fetchone(source_sql)
            rows = row_dicts(connection.execute(count_sql), ('label', 'count'))
        works = int(source[0]) if source else 0
        updated_at = docs.load_ts(source[1]) if source and source[1] else None
        source_updated_at = updated_at.isoformat() if hasattr(updated_at, 'isoformat') else updated_at
        return source_updated_at, works, {row['label']: int(row['count']) for row in rows}

    def get_insight_report(self, group: Optional[str], period: str,
                           owner: Optional[int] = None) -> Optional[dict]:
        group_clause = ('group_name IS NULL' if group is None
                        else 'group_name = ' + q(group))
        owner_clause = ('owner_id IS NULL' if owner is None
                        else 'owner_id = ' + q(int(owner)))
        with self._connect() as connection:
            row = first_row(connection.execute(
                'SELECT report, source_updated_at FROM insight_report WHERE '
                + group_clause + ' AND ' + owner_clause + ' AND period = ' + q(period)
                + ' ORDER BY created_at DESC LIMIT 1'),
                ('report', 'source_updated_at'))
        if row is None:
            return None
        report = row.get('report')
        if isinstance(report, str):
            report = json.loads(report)
        source_updated_at = docs.load_ts(row.get('source_updated_at'))
        return {'report': report, 'source_updated_at': source_updated_at}

    def save_insight_report(self, group: Optional[str], period: str, report: dict,
                            source_updated_at, owner: Optional[int] = None) -> None:
        owner_value = 'NULL' if owner is None else q(int(owner))
        with self._connect() as connection:
            connection.execute(
                'INSERT INTO insight_report(owner_id, group_name, period, report, '
                'source_updated_at, created_at) VALUES ('
                + owner_value + ', ' + sql_value(group) + ', ' + q(period) + ', '
                + sql_value(report) + ', ' + sql_value(source_updated_at)
                + ', now()) ON CONFLICT ((COALESCE(owner_id, 0)), '
                '(COALESCE(group_name, \'\')), period) '
                'DO UPDATE SET report = EXCLUDED.report, '
                'source_updated_at = EXCLUDED.source_updated_at, created_at = now()')

    # ---------------------------------------------------- integrity / counts

    def counts(self) -> dict:
        """Row counts of the tables owned by the storage layer."""
        result = {}
        with self._connect() as connection:
            for table in ('task', 'task_dds', 'task_incident_source',
                          '"session"', 'session_turn', 'session_hint',
                          'session_card_edit', 'session_reveal',
                          'machine_assessment', 'ai_assessment',
                          'ai_assessment_field', 'teacher_decision',
                          'teacher_decision_field', 'scenario', 'scenario_task',
                          'training', 'training_scenario',
                          'training_participant', 'training_card',
                          'training_service_action', 'material',
                          'workshop_card'):
                row = connection.fetchone('SELECT count(*) FROM ' + table)
                result[table.strip('"')] = int(row[0]) if row else 0
        return result