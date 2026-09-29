"""PostgreSQL persistence for the shared 112 trainer.

The browser/API contract stays unchanged.  Business objects keep their flexible JSON
shape, while identities and the relations that matter for multi-user work are also
projected into normalized tables for querying, integrity and reporting.

Local desktop mode does not import this driver unless DATABASE_URL/--database-url is
used.  Shared production mode should use PostgreSQL.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

SCHEMA_VERSION = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _now()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _payload(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _driver():
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            'Для PostgreSQL установите серверные зависимости: '
            'py -m pip install -r requirements-server.txt'
        ) from exc
    return psycopg, dict_row


MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, r'''
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
'''),
    (2, r'''
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
'''),
    (3, r'''
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
'''),
    (4, r'''
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
'''),
    (5, r'''
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_active ON auth_sessions(token_hash, expires_at) WHERE revoked_at IS NULL;
'''),
)


class PostgresStore:
    def __init__(self, dsn: str, *, auto_migrate: bool = False):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError('DATABASE_URL не задан.')
        if not re.match(r'^postgres(?:ql)?://', dsn.strip(), re.I):
            raise ValueError('DATABASE_URL должен начинаться с postgresql:// или postgres://.')
        self.dsn = dsn.strip()
        self._psycopg, self._dict_row = _driver()
        if auto_migrate:
            self.migrate()

    @contextmanager
    def connect(self):
        with self._psycopg.connect(self.dsn, row_factory=self._dict_row, connect_timeout=10) as conn:
            yield conn

    def health(self) -> dict:
        # Health must also work before the first migration so setup scripts can
        # distinguish "PostgreSQL is reachable" from "schema is ready".
        with self.connect() as conn:
            row = conn.execute('SELECT current_database() AS database, version() AS version').fetchone()
            exists = conn.execute("SELECT to_regclass('public.schema_migrations') AS table_name").fetchone()['table_name']
            if exists:
                version = conn.execute('SELECT COALESCE(max(version),0) AS version FROM schema_migrations').fetchone()['version']
            else:
                version = 0
        return {'backend': 'postgresql', 'database': row['database'], 'schema_version': int(version),
                'target_schema_version': SCHEMA_VERSION, 'ready': int(version) >= SCHEMA_VERSION}

    @staticmethod
    def _migration_statements(sql: str) -> list[str]:
        # The bundled migrations contain only plain DDL (no PL/pgSQL bodies),
        # therefore a semicolon splitter is both deterministic and compatible
        # with psycopg's extended-query protocol.  Executing one statement at a
        # time also gives useful errors on hosts that reject multi-statements.
        return [part.strip() for part in sql.split(';') if part.strip()]

    def migrate(self) -> int:
        with self.connect() as conn:
            # Serialise migrations even if two server processes start together.
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (1122026,))
            conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())')
            applied = {int(r['version']) for r in conn.execute('SELECT version FROM schema_migrations').fetchall()}
            for version, sql in MIGRATIONS:
                if version not in applied:
                    for statement in self._migration_statements(sql):
                        conn.execute(statement)
                    conn.execute('INSERT INTO schema_migrations(version) VALUES (%s)', (version,))
        return SCHEMA_VERSION

    # ----- engine tasks/sessions -------------------------------------------------
    def save_engine_item(self, item: dict) -> dict:
        identifier = item['id']
        kind = identifier[0]
        task_id = item.get('task', {}).get('id') if kind == 's' and isinstance(item.get('task'), dict) else None
        with self.connect() as conn:
            conn.execute('''
                INSERT INTO engine_items(id,kind,status,student,task_id,created_at,updated_at,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status, student=EXCLUDED.student,
                    task_id=EXCLUDED.task_id, updated_at=EXCLUDED.updated_at, payload=EXCLUDED.payload
            ''', (identifier, kind, item.get('status'), item.get('student'), task_id,
                  _dt(item.get('created_at')), _dt(item.get('updated_at')), _json(item)))
            if kind == 's':
                training_id = (item.get('training') or {}).get('training_id') if isinstance(item.get('training'), dict) else None
                result = item.get('result') or item.get('teacher_decision') or item.get('assessment') or {}
                grade = result.get('grade') if isinstance(result, dict) else None
                percent = result.get('percent') if isinstance(result, dict) else None
                conn.execute('''
                    INSERT INTO session_results(session_id,student_name,training_id,task_id,status,submitted_at,grade,percent,timed_out,updated_at,payload)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT(session_id) DO UPDATE SET student_name=EXCLUDED.student_name,training_id=EXCLUDED.training_id,
                        task_id=EXCLUDED.task_id,status=EXCLUDED.status,submitted_at=EXCLUDED.submitted_at,grade=EXCLUDED.grade,
                        percent=EXCLUDED.percent,timed_out=EXCLUDED.timed_out,updated_at=EXCLUDED.updated_at,payload=EXCLUDED.payload
                ''', (identifier,item.get('student'),training_id,task_id,item.get('status',''),
                      _dt(item.get('submitted_at')) if item.get('submitted_at') else None,
                      grade if type(grade) is int else None, percent if type(percent) is int else None,
                      bool(item.get('timed_out')), _dt(item.get('updated_at')), _json(item)))
        return item

    def load_engine_item(self, identifier: str) -> dict:
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM engine_items WHERE id=%s', (identifier,)).fetchone()
        if row is None:
            raise FileNotFoundError(identifier)
        return _payload(row['payload'])

    def engine_item_exists(self, identifier: str) -> bool:
        with self.connect() as conn:
            return conn.execute('SELECT 1 AS ok FROM engine_items WHERE id=%s', (identifier,)).fetchone() is not None

    def list_engine_items(self, kind: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('SELECT payload FROM engine_items WHERE kind=%s ORDER BY updated_at DESC', (kind,)).fetchall()
        return [_payload(r['payload']) for r in rows]

    def delete_engine_item(self, identifier: str) -> None:
        with self.connect() as conn:
            if conn.execute('DELETE FROM engine_items WHERE id=%s RETURNING id', (identifier,)).fetchone() is None:
                raise FileNotFoundError(identifier)

    # ----- scenarios/trainings ---------------------------------------------------
    def save_curriculum(self, item: dict) -> dict:
        kind = 'scenario' if item['id'].startswith('scenario-') else 'training'
        with self.connect() as conn:
            conn.execute('''
                INSERT INTO curriculum_resources(id,kind,status,title,teacher,room_code,created_at,updated_at,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(id) DO UPDATE SET status=EXCLUDED.status,title=EXCLUDED.title,
                    teacher=EXCLUDED.teacher,room_code=EXCLUDED.room_code,updated_at=EXCLUDED.updated_at,
                    payload=EXCLUDED.payload
            ''', (item['id'], kind, item.get('status',''), item.get('title',''), item.get('teacher') or item.get('created_by'),
                  item.get('room_code'), _dt(item.get('created_at')), _dt(item.get('updated_at')), _json(item)))
            if kind == 'scenario':
                conn.execute('DELETE FROM scenario_tasks WHERE scenario_id=%s', (item['id'],))
                levels = item.get('task_difficulties') or {}
                for pos, task_id in enumerate(item.get('task_ids', []), 1):
                    conn.execute('INSERT INTO scenario_tasks(scenario_id,task_id,position,difficulty) VALUES (%s,%s,%s,%s)',
                                 (item['id'], task_id, pos, int(levels.get(task_id, 3))))
            if kind == 'training':
                conn.execute('DELETE FROM training_scenarios WHERE training_id=%s', (item['id'],))
                for pos, scenario_id in enumerate(item.get('scenario_ids', []), 1):
                    conn.execute('INSERT INTO training_scenarios(training_id,scenario_id,position) VALUES (%s,%s,%s)',
                                 (item['id'], scenario_id, pos))
                conn.execute('DELETE FROM training_tasks WHERE training_id=%s', (item['id'],))
                for pos, task_id in enumerate(item.get('task_ids', []), 1):
                    conn.execute('INSERT INTO training_tasks(training_id,task_id,position) VALUES (%s,%s,%s)',
                                 (item['id'], task_id, pos))
                self._sync_training_projection(conn, item)
                conn.execute('''INSERT INTO training_events(training_id,actor,event_type,created_at,payload)
                                VALUES (%s,%s,'training_snapshot',%s,%s::jsonb)''',
                             (item['id'], item.get('teacher') or 'system', _dt(item.get('updated_at')),
                              _json({'status': item.get('status'), 'cards': len(item.get('cards',[])),
                                     'participants': len(item.get('participants',[]))})))
        return item

    def _sync_training_projection(self, conn, item: dict) -> None:
        tid = item['id']
        conn.execute('DELETE FROM training_participants WHERE training_id=%s', (tid,))
        for p in item.get('participants', []):
            conn.execute('''
                INSERT INTO training_participants(training_id,participant_id,user_id,student_name,training_role,service,joined_at)
                VALUES (%s,%s,(SELECT id FROM app_users WHERE lower(full_name)=lower(%s) LIMIT 1),%s,%s,%s,%s)
            ''', (tid, p.get('id'), p.get('student'), p.get('student'), p.get('role'), p.get('service',''), _dt(p.get('joined_at'))))
        conn.execute('DELETE FROM training_cards WHERE training_id=%s', (tid,))
        for card in item.get('cards', []):
            conn.execute('''
                INSERT INTO training_cards(training_id,card_id,operator_session_id,task_id,student_name,status,dds_by,
                                           submitted_at,routed_at,updated_at,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ''', (tid, card.get('id'), card.get('operator_session_id'), card.get('task_id'), card.get('student'),
                  card.get('status',''), card.get('dds_by'), _dt(card.get('submitted_at')) if card.get('submitted_at') else None,
                  _dt(card.get('routed_at')) if card.get('routed_at') else None, _dt(item.get('updated_at')), _json(card)))

    def load_curriculum(self, identifier: str) -> dict:
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM curriculum_resources WHERE id=%s', (identifier,)).fetchone()
        if row is None:
            raise FileNotFoundError(identifier)
        return _payload(row['payload'])

    def list_curriculum(self, kind: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('SELECT payload FROM curriculum_resources WHERE kind=%s ORDER BY created_at DESC', (kind,)).fetchall()
        return [_payload(r['payload']) for r in rows]

    def delete_curriculum(self, identifier: str) -> None:
        with self.connect() as conn:
            if conn.execute('DELETE FROM curriculum_resources WHERE id=%s RETURNING id', (identifier,)).fetchone() is None:
                raise FileNotFoundError(identifier)

    def append_training_event(self, training_id: str, event_type: str, *, actor: str = '', card_id: str | None = None, payload: dict | None = None) -> None:
        with self.connect() as conn:
            conn.execute('''INSERT INTO training_events(training_id,card_id,actor,event_type,payload)
                            VALUES (%s,%s,%s,%s,%s::jsonb)''',
                         (training_id, card_id, actor or None, event_type, _json(payload or {})))

    # ----- materials -------------------------------------------------------------
    def list_materials(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('SELECT payload FROM materials ORDER BY created_at').fetchall()
        return [_payload(r['payload']) for r in rows]

    def add_material(self, item: dict) -> dict:
        with self.connect() as conn:
            conn.execute('''INSERT INTO materials(id,title,url,description,teacher,created_at,payload)
                            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                            ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title,url=EXCLUDED.url,
                                description=EXCLUDED.description,teacher=EXCLUDED.teacher,payload=EXCLUDED.payload''',
                         (item['id'], item['title'], item['url'], item.get('description',''), item['teacher'],
                          _dt(item.get('created_at')), _json(item)))
        return item

    # ----- teacher workshop / shared settings ------------------------------------
    def load_workshop_state(self, user_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM workshop_states WHERE user_id=%s', (int(user_id),)).fetchone()
        return _payload(row['payload']) if row else None

    def save_workshop_state(self, user_id: int, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError('Состояние мастерской должно быть JSON-объектом.')
        with self.connect() as conn:
            conn.execute('''
                INSERT INTO workshop_states(user_id,payload,updated_at) VALUES (%s,%s::jsonb,now())
                ON CONFLICT(user_id) DO UPDATE SET payload=EXCLUDED.payload, updated_at=now()
            ''', (int(user_id), _json(payload)))
        return payload

    def load_setting(self, key: str) -> Any:
        with self.connect() as conn:
            row = conn.execute('SELECT payload FROM system_settings WHERE key=%s', (key,)).fetchone()
        return _payload(row['payload']) if row else None

    def save_setting(self, key: str, payload: Any) -> Any:
        with self.connect() as conn:
            conn.execute('''
                INSERT INTO system_settings(key,payload,updated_at) VALUES (%s,%s::jsonb,now())
                ON CONFLICT(key) DO UPDATE SET payload=EXCLUDED.payload, updated_at=now()
            ''', (key, _json(payload)))
        return payload

    # ----- users -----------------------------------------------------------------
    def user_count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute('SELECT count(*) AS n FROM app_users').fetchone()['n'])

    def create_user(self, *, login: str, full_name: str, role: str, salt: bytes, password_hash: bytes, created_at: str) -> dict:
        try:
            with self.connect() as conn:
                row = conn.execute('''INSERT INTO app_users(login,full_name,role,salt,password_hash,created_at,updated_at)
                                      VALUES (%s,%s,%s,%s,%s,%s,%s)
                                      RETURNING id,login,full_name,role,active,created_at,last_login_at''',
                                   (login, full_name, role, salt, password_hash, _dt(created_at), _dt(created_at))).fetchone()
        except self._psycopg.errors.UniqueViolation:
            raise ValueError('Логин или имя уже зарегистрированы.') from None
        return self._public_user(row)

    def get_user_by_login(self, login: str, *, active_only: bool = True) -> dict | None:
        sql = 'SELECT * FROM app_users WHERE login=%s' + (' AND active=true' if active_only else '')
        with self.connect() as conn:
            row = conn.execute(sql, (login,)).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute('SELECT id,login,full_name,role,active,created_at,last_login_at FROM app_users ORDER BY id').fetchall()
        return [self._public_user(r) for r in rows]

    def create_auth_session(self, *, session_id: str, user_id: int, token_hash: bytes, created_at: datetime, expires_at: datetime) -> None:
        with self.connect() as conn:
            conn.execute('DELETE FROM auth_sessions WHERE expires_at <= now() OR revoked_at IS NOT NULL')
            row = conn.execute('SELECT id FROM app_users WHERE id=%s AND active=true', (int(user_id),)).fetchone()
            if not row:
                raise ValueError('Пользователь не найден или заблокирован.')
            conn.execute('''INSERT INTO auth_sessions(id,user_id,token_hash,created_at,expires_at)
                            VALUES (%s::uuid,%s,%s,%s,%s)''',
                         (session_id, int(user_id), token_hash, created_at, expires_at))
            conn.execute('UPDATE app_users SET last_login_at=%s,updated_at=%s WHERE id=%s',
                         (created_at, created_at, int(user_id)))

    def get_user_by_session_hash(self, token_hash: bytes) -> dict | None:
        with self.connect() as conn:
            row = conn.execute('''SELECT u.* FROM auth_sessions s
                                  JOIN app_users u ON u.id=s.user_id
                                  WHERE s.token_hash=%s AND s.revoked_at IS NULL
                                    AND s.expires_at>now() AND u.active=true''', (token_hash,)).fetchone()
        return dict(row) if row else None

    def revoke_auth_session(self, token_hash: bytes) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL', (token_hash,))

    def revoke_user_sessions(self, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute('UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (int(user_id),))

    def update_password(self, user_id: int, *, salt: bytes, password_hash: bytes) -> None:
        with self.connect() as conn:
            row = conn.execute('UPDATE app_users SET salt=%s,password_hash=%s,updated_at=%s WHERE id=%s RETURNING id',
                               (salt, password_hash, _now(), user_id)).fetchone()
        if not row:
            raise ValueError('Пользователь не найден.')

    def update_user(self, user_id: int, *, role: str | None = None, active: bool | None = None, full_name: str | None = None) -> dict:
        changes, values = [], []
        for column, value in (('role',role),('active',active),('full_name',full_name)):
            if value is not None:
                changes.append(f'{column}=%s'); values.append(value)
        if not changes:
            raise ValueError('Не указаны изменения пользователя.')
        values.extend([_now(), user_id])
        try:
            with self.connect() as conn:
                row = conn.execute(f'''UPDATE app_users SET {','.join(changes)},updated_at=%s WHERE id=%s
                                       RETURNING id,login,full_name,role,active,created_at,last_login_at''', values).fetchone()
        except self._psycopg.errors.UniqueViolation:
            raise ValueError('Имя уже используется другой учётной записью.') from None
        if not row:
            raise ValueError('Пользователь не найден.')
        return self._public_user(row)

    @staticmethod
    def _public_user(row: dict) -> dict:
        out = dict(row)
        for key in ('created_at','last_login_at'):
            if isinstance(out.get(key), datetime):
                out[key] = out[key].isoformat()
        if 'last_login_at' in out:
            out['last_login'] = out.pop('last_login_at')
        return out


def store_from_url(database_url: str | None = None, *, auto_migrate: bool = False) -> PostgresStore | None:
    dsn = database_url if database_url is not None else os.environ.get('DATABASE_URL')
    return PostgresStore(dsn, auto_migrate=auto_migrate) if dsn else None
