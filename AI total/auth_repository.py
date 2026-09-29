"""Database access for the auth layer: schema, users, groups and sessions.

Direct PostgreSQL access via db_connection (Simple Query protocol). Every call
opens and closes its own connection, mirroring the project's data_layer
pattern; connection pooling is a later optimisation. Untrusted values are
always embedded through db_connection.quote_literal().
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import db_config
import db_connection
from db_connection import quote_literal as q

USER_ROLES = ('admin', 'teacher', 'student')
SCHEMA_VERSION = '2.1.0'

# -------------------------------------------------------------------- DDL

SCHEMA_STATEMENTS = [
    # Users. "user" is a reserved word, so it is always quoted.
    """
    CREATE TABLE IF NOT EXISTS "user" (
        id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        login         text NOT NULL UNIQUE,
        password_hash text NOT NULL,
        full_name     text NOT NULL DEFAULT '',
        display_name  text,
        role          text NOT NULL DEFAULT 'student'
                      CHECK (role IN ('admin', 'teacher', 'student')),
        is_active     boolean NOT NULL DEFAULT true,
        created_at    timestamptz NOT NULL DEFAULT now(),
        updated_at    timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_user_role ON "user"(role)',
    'CREATE INDEX IF NOT EXISTS idx_user_active ON "user"(is_active)',
    """
    CREATE TABLE IF NOT EXISTS student_group (
        id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name        text NOT NULL UNIQUE,
        description text NOT NULL DEFAULT '',
        teacher_id  bigint REFERENCES "user"(id) ON DELETE SET NULL,
        created_at  timestamptz NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_group_teacher ON student_group(teacher_id)',
    """
    CREATE TABLE IF NOT EXISTS group_member (
        group_id bigint NOT NULL REFERENCES student_group(id) ON DELETE CASCADE,
        user_id  bigint NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        added_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (group_id, user_id)
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_group_member_user ON group_member(user_id)',
    """
    CREATE TABLE IF NOT EXISTS auth_session (
        id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id         bigint NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
        refresh_hash    text NOT NULL UNIQUE,
        created_at      timestamptz NOT NULL DEFAULT now(),
        expires_at      timestamptz NOT NULL,
        revoked_at      timestamptz,
        replaced_by_id  bigint REFERENCES auth_session(id) ON DELETE SET NULL,
        user_agent      text NOT NULL DEFAULT ''
    )
    """,
    'CREATE INDEX IF NOT EXISTS idx_auth_session_user ON auth_session(user_id)',
    'CREATE INDEX IF NOT EXISTS idx_auth_session_expires ON auth_session(expires_at)',
    """
    CREATE TABLE IF NOT EXISTS schema_migration (
        version    text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
    )
    """,
]

# Column list shared by SELECTs returning full user rows. Order is important:
# it must match _user_from_row().
_USER_COLUMNS = ('id', 'login', 'password_hash', 'full_name', 'display_name',
                 'role', 'is_active', 'created_at', 'updated_at')


class AuthRepository:
    """CRUD over users, student groups and auth sessions."""

    def __init__(self, config: Optional[Dict[str, object]] = None):
        self._config = config or db_config.get_db_config()

    def _connect(self) -> db_connection.PostgresConnection:
        return db_connection.connection_from_config(self._config)

    # ----------------------------------------------------------------- schema

    def ensure_schema(self) -> None:
        """Create missing tables/indexes and record the migration version."""
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

    # ------------------------------------------------------------------ users

    @staticmethod
    def _as_bool(value) -> Optional[bool]:
        """Convert a PostgreSQL boolean (text 't'/'f') to a Python bool."""
        if value is None:
            return None
        return str(value).strip().lower() in ('t', 'true', '1')

    def _user_from_row(self, row) -> Optional[dict]:
        if row is None:
            return None
        data = dict(zip(_USER_COLUMNS, row))
        data['is_active'] = self._as_bool(data['is_active'])
        return data

    def find_by_login(self, login: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(_USER_COLUMNS) + ' FROM "user" WHERE login = ' + q(login))
        return self._user_from_row(row)

    def find_by_id(self, user_id: int) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(_USER_COLUMNS) + ' FROM "user" WHERE id = ' + q(int(user_id)))
        return self._user_from_row(row)

    def list_users(self, role: Optional[str] = None) -> List[dict]:
        where = ' WHERE role = ' + q(role) if role is not None else ''
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_USER_COLUMNS) + ' FROM "user"'
                + where + ' ORDER BY role, login')
        return [self._user_from_row(row) for row in rows]

    def list_students_by_ids(self, user_ids: List[int]) -> List[dict]:
        if not user_ids:
            return []
        identifiers = ', '.join(q(int(user_id)) for user_id in sorted(set(user_ids)))
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join(_USER_COLUMNS) + ' FROM "user"'
                ' WHERE role = ' + q('student') + ' AND id IN (' + identifiers + ')'
                ' ORDER BY login')
        return [self._user_from_row(row) for row in rows]

    def list_students_in_group(self, group_id: int) -> List[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT ' + ', '.join('u.' + column for column in _USER_COLUMNS)
                + ' FROM group_member m JOIN "user" u ON u.id = m.user_id'
                ' WHERE m.group_id = ' + q(int(group_id))
                + ' AND u.role = ' + q('student') + ' ORDER BY u.login')
        return [self._user_from_row(row) for row in rows]

    def count_users(self) -> int:
        with self._connect() as connection:
            row = connection.fetchone('SELECT count(*) FROM "user"')
        return int(row[0]) if row else 0

    def create_user(self, login: str, password_hash: str, full_name: str,
                    role: str, display_name: Optional[str] = None) -> dict:
        assert role in USER_ROLES
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO "user"(login, password_hash, full_name, role, display_name) '
                'VALUES (' + q(login) + ', ' + q(password_hash) + ', ' + q(full_name)
                + ', ' + q(role) + ', ' + q(display_name) + ') RETURNING '
                + ', '.join(_USER_COLUMNS))
        return self._user_from_row(rows[0])

    def update_user(self, user_id: int, *, password_hash: Optional[str] = None,
                    full_name: Optional[str] = None, display_name: Optional[str] = None,
                    role: Optional[str] = None, is_active: Optional[bool] = None,
                    login: Optional[str] = None) -> Optional[dict]:
        if role is not None:
            assert role in USER_ROLES
        sets = []
        if login is not None:
            sets.append('login = ' + q(login))
        if password_hash is not None:
            sets.append('password_hash = ' + q(password_hash))
        if full_name is not None:
            sets.append('full_name = ' + q(full_name))
        if display_name is not None:
            sets.append('display_name = ' + q(display_name))
        if role is not None:
            sets.append('role = ' + q(role))
        if is_active is not None:
            sets.append('is_active = ' + ('TRUE' if is_active else 'FALSE'))
        if not sets:
            return self.find_by_id(user_id)
        sets.append('updated_at = now()')
        with self._connect() as connection:
            rows = connection.execute(
                'UPDATE "user" SET ' + ', '.join(sets) + ' WHERE id = ' + q(int(user_id))
                + ' RETURNING ' + ', '.join(_USER_COLUMNS))
        return self._user_from_row(rows[0] if rows else None)

    def delete_user(self, user_id: int) -> bool:
        with self._connect() as connection:
            connection.execute('DELETE FROM "user" WHERE id = ' + q(int(user_id)))
            return connection.rowcount > 0

    def set_password(self, user_id: int, password_hash: str) -> None:
        self.update_user(user_id, password_hash=password_hash)

    # ----------------------------------------------------------------- groups

    _GROUP_COLUMNS = ('id', 'name', 'description', 'teacher_id', 'created_at')

    def _group_from_row(self, row) -> Optional[dict]:
        if row is None:
            return None
        return dict(zip(self._GROUP_COLUMNS, row))

    def list_groups(self) -> List[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT g.id, g.name, g.description, g.teacher_id, g.created_at,'
                ' (SELECT count(*) FROM group_member m WHERE m.group_id = g.id) AS member_count,'
                ' (SELECT u.full_name FROM "user" u WHERE u.id = g.teacher_id) AS teacher_name'
                ' FROM student_group g ORDER BY g.name')
        return [{'id': row[0], 'name': row[1], 'description': row[2],
                 'teacher_id': row[3], 'created_at': row[4],
                 'member_count': int(row[5] or 0), 'teacher_name': row[6]}
                for row in rows]

    def get_group(self, group_id: int) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT ' + ', '.join(self._GROUP_COLUMNS) + ' FROM student_group WHERE id = ' + q(int(group_id)))
        return self._group_from_row(row)

    def create_group(self, name: str, description: str,
                     teacher_id: Optional[int] = None) -> dict:
        teacher = 'NULL' if teacher_id is None else q(int(teacher_id))
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO student_group(name, description, teacher_id) VALUES ('
                + q(name) + ', ' + q(description) + ', ' + teacher + ') RETURNING '
                + ', '.join(self._GROUP_COLUMNS))
        return self._group_from_row(rows[0])

    def update_group(self, group_id: int, *, name: Optional[str] = None,
                     description: Optional[str] = None,
                     teacher_id: Optional[int] = None,
                     clear_teacher: bool = False) -> Optional[dict]:
        sets = []
        if name is not None:
            sets.append('name = ' + q(name))
        if description is not None:
            sets.append('description = ' + q(description))
        if clear_teacher:
            sets.append('teacher_id = NULL')
        elif teacher_id is not None:
            sets.append('teacher_id = ' + q(int(teacher_id)))
        if not sets:
            return self.get_group(group_id)
        with self._connect() as connection:
            rows = connection.execute(
                'UPDATE student_group SET ' + ', '.join(sets)
                + ' WHERE id = ' + q(int(group_id)) + ' RETURNING '
                + ', '.join(self._GROUP_COLUMNS))
        return self._group_from_row(rows[0] if rows else None)

    def delete_group(self, group_id: int) -> bool:
        with self._connect() as connection:
            connection.execute('DELETE FROM student_group WHERE id = ' + q(int(group_id)))
            return connection.rowcount > 0

    def list_group_members(self, group_id: int) -> List[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT u.id, u.login, u.full_name, u.role, u.is_active, m.added_at'
                ' FROM group_member m JOIN "user" u ON u.id = m.user_id'
                ' WHERE m.group_id = ' + q(int(group_id)) + ' ORDER BY u.login')
        return [{'id': row[0], 'login': row[1], 'full_name': row[2],
                 'role': row[3], 'is_active': self._as_bool(row[4]),
                 'added_at': row[5]}
                for row in rows]

    def add_group_member(self, group_id: int, user_id: int) -> bool:
        with self._connect() as connection:
            connection.execute(
                'INSERT INTO group_member(group_id, user_id) VALUES ('
                + q(int(group_id)) + ', ' + q(int(user_id))
                + ') ON CONFLICT (group_id, user_id) DO NOTHING')
            return connection.rowcount > 0

    def remove_group_member(self, group_id: int, user_id: int) -> bool:
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM group_member WHERE group_id = ' + q(int(group_id))
                + ' AND user_id = ' + q(int(user_id)))
            return connection.rowcount > 0

    # ----------------------------------------------------------- auth sessions

    def create_session(self, user_id: int, refresh_hash: str,
                       expires_at: datetime, user_agent: str = '') -> int:
        with self._connect() as connection:
            rows = connection.execute(
                'INSERT INTO auth_session(user_id, refresh_hash, expires_at, user_agent)'
                ' VALUES (' + q(int(user_id)) + ', ' + q(refresh_hash) + ', '
                + q(expires_at.isoformat()) + ', ' + q(user_agent)
                + ') RETURNING id')
        return int(rows[0][0])

    def find_session_by_hash(self, refresh_hash: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.fetchone(
                'SELECT id, user_id, refresh_hash, created_at, expires_at, revoked_at,'
                ' replaced_by_id, user_agent FROM auth_session WHERE refresh_hash = '
                + q(refresh_hash))
        if row is None:
            return None
        return {'id': row[0], 'user_id': row[1], 'refresh_hash': row[2],
                'created_at': row[3], 'expires_at': row[4], 'revoked_at': row[5],
                'replaced_by_id': row[6], 'user_agent': row[7]}

    def revoke_session(self, session_id: int, replaced_by_id: Optional[int] = None) -> None:
        replaced = '' if replaced_by_id is None else ', replaced_by_id = ' + q(int(replaced_by_id))
        with self._connect() as connection:
            connection.execute(
                'UPDATE auth_session SET revoked_at = now()' + replaced
                + ' WHERE id = ' + q(int(session_id)))

    def revoke_user_sessions(self, user_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                'UPDATE auth_session SET revoked_at = now()'
                ' WHERE user_id = ' + q(int(user_id)) + ' AND revoked_at IS NULL')

    def expire_old_sessions(self, days: int = 7) -> int:
        """Purge revoked or expired sessions older than N days (housekeeping)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM auth_session WHERE revoked_at IS NOT NULL AND revoked_at < '
                + q(cutoff) + ' OR expires_at < ' + q(cutoff))
            return connection.rowcount