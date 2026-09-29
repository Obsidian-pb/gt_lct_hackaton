"""Server-side identities for shared classroom/server deployment.

In PostgreSQL mode accounts and browser sessions live in the same database as
trainings. Local/legacy mode keeps a small SQLite file so the desktop trainer and
unit tests can still run without external services.
"""
import base64
from contextlib import contextmanager
import binascii
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
from pathlib import Path
import secrets
import sqlite3
import uuid


ROLES = frozenset({'admin', 'teacher', 'student'})
ITERATIONS = 260_000
SESSION_TTL_SECONDS = 12 * 60 * 60


def _validate_identity(login, full_name, role, password):
    login = login.strip().casefold()
    full_name = full_name.strip()
    if not login or len(login) > 64 or not all(c.isascii() and (c.isalnum() or c in '._-') for c in login):
        raise ValueError('Логин: латинские буквы, цифры, точка, дефис или подчёркивание (до 64).')
    if not 2 <= len(full_name) <= 160 or role not in ROLES or len(password) < 10:
        raise ValueError('Укажите имя (2–160 знаков), роль и пароль от 10 символов.')
    return login, full_name


def _hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt, hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)


def _verify_password(row, password):
    if not row or not isinstance(password, str):
        return False
    salt = bytes(row['salt'])
    password_hash = bytes(row['password_hash'])
    expected = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
    return hmac.compare_digest(expected, password_hash)


def _public_user(row):
    return {'id': row['id'], 'login': row['login'], 'full_name': row['full_name'], 'role': row['role']}


class Accounts:
    def __init__(self, directory, store=None):
        self.store = store
        self.path = Path(directory) / 'accounts.sqlite3'
        if self.store is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as db:
                db.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
                    salt BLOB NOT NULL, password_hash BLOB NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
                )''')
                db.execute('''CREATE TABLE IF NOT EXISTS auth_sessions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash BLOB NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                )''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def count(self):
        if self.store is not None:
            return self.store.user_count()
        with self._connect() as db:
            return db.execute('SELECT count(*) FROM users').fetchone()[0]

    def create(self, login, full_name, role, password):
        login, full_name = _validate_identity(login, full_name, role, password)
        salt, password_hash = _hash_password(password)
        created = datetime.now(timezone.utc).isoformat()
        if self.store is not None:
            return self.store.create_user(login=login, full_name=full_name, role=role, salt=salt,
                                          password_hash=password_hash, created_at=created)
        try:
            with self._connect() as db:
                cur = db.execute('INSERT INTO users (login,full_name,role,salt,password_hash,created_at) VALUES (?,?,?,?,?,?)',
                                 (login, full_name, role, salt, password_hash, created))
                user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('Логин или имя уже зарегистрированы.') from None
        return next(row for row in self.list_users() if row['id'] == user_id)

    def authenticate_credentials(self, login, password):
        if not isinstance(login, str) or not isinstance(password, str):
            return None
        login = login.strip().casefold()
        if not login or len(login) > 64 or len(password) > 4096:
            return None
        if self.store is not None:
            row = self.store.get_user_by_login(login, active_only=True)
        else:
            with self._connect() as db:
                fetched = db.execute('SELECT * FROM users WHERE login = ? AND active = 1', (login,)).fetchone()
                row = dict(fetched) if fetched else None
        return _public_user(row) if _verify_password(row, password) else None

    def authenticate(self, authorization):
        """Compatibility authentication for scripts/API clients using HTTP Basic."""
        if not authorization or not authorization.startswith('Basic ') or len(authorization) > 4096:
            return None
        try:
            raw = base64.b64decode(authorization[6:].strip(), validate=True).decode('utf-8')
            login, password = raw.split(':', 1)
        except (ValueError, UnicodeError, binascii.Error):
            return None
        return self.authenticate_credentials(login, password)

    def create_session(self, user_id, ttl_seconds=SESSION_TTL_SECONDS):
        if not isinstance(ttl_seconds, int) or not 300 <= ttl_seconds <= 7 * 24 * 60 * 60:
            raise ValueError('Некорректное время жизни сессии.')
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode('ascii')).digest()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        session_id = str(uuid.uuid4())
        if self.store is not None:
            self.store.create_auth_session(session_id=session_id, user_id=int(user_id), token_hash=token_hash,
                                           created_at=now, expires_at=expires)
        else:
            with self._connect() as db:
                db.execute('DELETE FROM auth_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL', (now.isoformat(),))
                db.execute('''INSERT INTO auth_sessions(id,user_id,token_hash,created_at,expires_at)
                              VALUES (?,?,?,?,?)''',
                           (session_id, int(user_id), token_hash, now.isoformat(), expires.isoformat()))
        return token

    def authenticate_session(self, token):
        if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii():
            return None
        token_hash = hashlib.sha256(token.encode('ascii')).digest()
        if self.store is not None:
            row = self.store.get_user_by_session_hash(token_hash)
            return _public_user(row) if row else None
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            fetched = db.execute('''SELECT u.* FROM auth_sessions s
                                    JOIN users u ON u.id=s.user_id
                                    WHERE s.token_hash=? AND s.revoked_at IS NULL
                                      AND s.expires_at>? AND u.active=1''', (token_hash, now)).fetchone()
        return _public_user(dict(fetched)) if fetched else None

    def revoke_session(self, token):
        if not isinstance(token, str) or not token:
            return
        token_hash = hashlib.sha256(token.encode('ascii', errors='ignore')).digest()
        if self.store is not None:
            self.store.revoke_auth_session(token_hash)
            return
        with self._connect() as db:
            db.execute('UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL',
                       (datetime.now(timezone.utc).isoformat(), token_hash))

    def revoke_user_sessions(self, user_id):
        if self.store is not None:
            self.store.revoke_user_sessions(int(user_id))
            return
        with self._connect() as db:
            db.execute('UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',
                       (datetime.now(timezone.utc).isoformat(), int(user_id)))

    def list_users(self):
        if self.store is not None:
            return self.store.list_users()
        with self._connect() as db:
            cur = db.execute('SELECT id,login,full_name,role,active,created_at FROM users ORDER BY id')
            try:
                rows = cur.fetchall()
            finally:
                cur.close()
        return [dict(row) for row in rows]

    def update(self, user_id, *, role=None, active=None, full_name=None):
        if role is not None and role not in ROLES:
            raise ValueError('Неизвестная системная роль.')
        current = next((u for u in self.list_users() if int(u['id']) == int(user_id)), None)
        if current is None:
            raise ValueError('Пользователь не найден.')
        removes_admin = current['role'] == 'admin' and bool(current['active']) and (role not in (None, 'admin') or active is False)
        if removes_admin:
            other_admins = [u for u in self.list_users() if int(u['id']) != int(user_id) and u['role'] == 'admin' and bool(u['active'])]
            if not other_admins:
                raise ValueError('Нельзя отключить или понизить последнего активного администратора.')
        if full_name is not None:
            full_name = full_name.strip()
            if not 2 <= len(full_name) <= 160:
                raise ValueError('Имя: от 2 до 160 символов.')
        if active is not None and type(active) is not bool:
            raise ValueError('active должен быть true или false.')
        if self.store is not None:
            updated = self.store.update_user(int(user_id), role=role, active=active, full_name=full_name)
            if active is False:
                self.revoke_user_sessions(user_id)
            return updated
        changes, values = [], []
        for column, value in (('role',role),('active',1 if active else 0 if active is not None else None),('full_name',full_name)):
            if value is not None:
                changes.append(f'{column}=?'); values.append(value)
        if not changes:
            raise ValueError('Не указаны изменения пользователя.')
        values.append(int(user_id))
        try:
            with self._connect() as db:
                cur = db.execute(f"UPDATE users SET {','.join(changes)} WHERE id=?", values)
                if not cur.rowcount:
                    raise ValueError('Пользователь не найден.')
        except sqlite3.IntegrityError:
            raise ValueError('Имя уже используется другой учётной записью.') from None
        if active is False:
            self.revoke_user_sessions(user_id)
        return next(row for row in self.list_users() if row['id'] == int(user_id))

    def set_password(self, user_id, password):
        if not isinstance(password, str) or len(password) < 10:
            raise ValueError('Пароль должен содержать не менее 10 символов.')
        salt, password_hash = _hash_password(password)
        if self.store is not None:
            self.store.update_password(int(user_id), salt=salt, password_hash=password_hash)
            self.revoke_user_sessions(user_id)
            return
        with self._connect() as db:
            cur = db.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?', (salt,password_hash,int(user_id)))
            if not cur.rowcount:
                raise ValueError('Пользователь не найден.')
        self.revoke_user_sessions(user_id)


def check_action(user, action, payload):
    """Check server identity against the names the existing client supplies."""
    role = user['role']
    if role == 'admin':
        return
    common = {'home', 'card_meta', 'services_list', 'tts_status', 'tts_synthesize',
              'materials_list', 'geo_addresses', 'geo_map', 'training_find_lobby',
              'training_lobby'}
    student_actions = {'student_overview', 'student_start', 'student_action', 'start',
                       'student', 'ask', 'hint', 'save_card', 'submit', 'connect',
                       'channel', 'training_join', 'training_desk', 'training_dial_callback',
                       'training_hangup_callback', 'training_dispatcher_examples',
                       'training_service_open', 'training_senior_answer',
                       'training_dds_senior_answer', 'training_service_route',
                       'training_dds_service_route', 'training_route',
                       'training_callback', 'training_service_action'}
    if action not in common and not (role == 'student' and action in student_actions) and role != 'teacher':
        raise PermissionError('У этой учётной записи нет доступа к действию.')
    if role == 'teacher' and action in student_actions:
        raise PermissionError('Рабочее место обучающегося доступно обучающемуся.')
    if role == 'student':
        for key in ('student',):
            if key in payload and payload[key] != user['full_name']:
                raise PermissionError('В запросе указан другой обучающийся.')
    if role == 'teacher' and 'teacher' in payload and payload['teacher'] != user['full_name']:
        raise PermissionError('В запросе указан другой преподаватель.')
