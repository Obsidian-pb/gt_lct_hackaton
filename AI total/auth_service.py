"""Auth business logic: login, tokens, RBAC and admin/user/group operations.

Raises AuthError(status, code, message); HTTP handlers map it to APIError.
Zero third-party dependencies — all cryptography comes from auth_crypto.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import auth_crypto
import auth_repository
from auth_crypto import get_auth_config, ensure_jwt_secret, hash_password, verify_password

USER_ROLES = auth_repository.USER_ROLES


class AuthError(Exception):
    """Authentication/authorization failure with an HTTP-like status."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def _public_user(user: Optional[dict]) -> Optional[dict]:
    if user is None:
        return None
    return {key: user[key] for key in ('id', 'login', 'full_name', 'display_name',
                                       'role', 'is_active', 'created_at', 'updated_at')}


def _user_required(user: Optional[dict]) -> dict:
    if user is None or not user.get('is_active'):
        raise AuthError(401, 'unauthorized', 'Пользователь не найден или деактивирован.')
    return user


# --------------------------------------------------------------------- tokens

def _issue_pair(repository, user: dict, user_agent: str) -> dict:
    config = get_auth_config()
    secret = ensure_jwt_secret()
    access_token = auth_crypto.issue_access_token(
        user['id'], user['login'], user['role'], secret, config['access_ttl'])
    raw_refresh, refresh_hash = auth_crypto.new_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=config['refresh_ttl'])
    repository.create_session(user['id'], refresh_hash, expires_at, user_agent or '')
    return {'access_token': access_token, 'refresh_token': raw_refresh,
            'expires_in': config['access_ttl'], 'user': _public_user(user)}


def authenticate_access_token(authorization: str) -> dict:
    """Verify an Authorization header ('Bearer <jwt>') and return the user."""
    if not authorization or not authorization.startswith('Bearer '):
        raise AuthError(401, 'unauthorized', 'Требуется заголовок Authorization: Bearer <token>.')
    token = authorization[len('Bearer '):].strip()
    if not token:
        raise AuthError(401, 'unauthorized', 'Пустой токен доступа.')
    try:
        claims = auth_crypto.decode_jwt(token, ensure_jwt_secret(), max_age=86400 * 3)
    except auth_crypto.AuthCryptoError as exc:
        raise AuthError(401, 'invalid_token', str(exc)) from None
    try:
        user_id = int(claims['sub'])
    except (KeyError, TypeError, ValueError):
        raise AuthError(401, 'invalid_token', 'Токен не содержит корректного идентификатора пользователя.') from None
    return _user_required(auth_repository.AuthRepository().find_by_id(user_id))


def require_role(user: dict, roles) -> None:
    """Raise 403 unless user.role is one of the allowed roles."""
    if not user or user.get('role') not in roles:
        raise AuthError(403, 'forbidden', 'Недостаточно прав для этой операции.')


def owner_key(user: Optional[dict]) -> Optional[str]:
    """Return the stable legacy identity represented by an authenticated user."""
    if not user:
        return None
    for key in ('display_name', 'login', 'full_name'):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def require_owner(user: dict, owner) -> None:
    """Reject access to a legacy-owned record unless its owner is the caller."""
    if user and user.get('role') == 'admin':
        return
    identity = owner_key(user)
    if not identity or not isinstance(owner, str) or identity.casefold() != owner.strip().casefold():
        raise AuthError(403, 'wrong_owner', 'Этот ресурс принадлежит другому пользователю.')


def roles_required() -> bool:
    """Этап 5: enforce JWT roles on every REST route (config auth.require_roles)."""
    return bool(auth_crypto.get_auth_config().get('require_roles'))


# -------------------------------------------------------------------- session

def login(login: str, password: str, user_agent: str = '') -> dict:
    """Authenticate by login/password and issue an access+refresh token pair."""
    if not login or not password:
        raise AuthError(422, 'missing_credentials', 'Укажите логин и пароль.')
    repository = auth_repository.AuthRepository()
    user = repository.find_by_login(login)
    if user is None or not verify_password(password, user['password_hash']):
        raise AuthError(401, 'wrong_credentials', 'Неверный логин или пароль.')
    _user_required(user)
    return _issue_pair(repository, user, user_agent)


def _as_utc(value) -> datetime:
    """Normalize a timestamptz returned by the client (ISO text) to aware UTC."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def refresh(refresh_token: str, user_agent: str = '') -> dict:
    """Rotate a refresh token: revoke the old one and issue a new pair."""
    if not refresh_token:
        raise AuthError(422, 'missing_refresh', 'Укажите refresh_token.')
    repository = auth_repository.AuthRepository()
    import hashlib
    provided_hash = hashlib.sha256(refresh_token.encode('ascii')).hexdigest()
    session = repository.find_session_by_hash(provided_hash)
    if session is None or session['revoked_at'] is not None:
        raise AuthError(401, 'invalid_refresh', 'Refresh-токен недействителен или отозван.')
    if _as_utc(session['expires_at']) < datetime.now(timezone.utc):
        raise AuthError(401, 'invalid_refresh', 'Срок действия refresh-токена истёк.')
    user = _user_required(repository.find_by_id(session['user_id']))
    # Create the replacement session first, then revoke the old one.
    config = get_auth_config()
    new_raw, new_hash = auth_crypto.new_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=config['refresh_ttl'])
    new_session_id = repository.create_session(user['id'], new_hash, expires_at, user_agent or '')
    repository.revoke_session(session['id'], replaced_by_id=new_session_id)
    secret = ensure_jwt_secret()
    access_token = auth_crypto.issue_access_token(
        user['id'], user['login'], user['role'], secret, config['access_ttl'])
    return {'access_token': access_token, 'refresh_token': new_raw,
            'expires_in': config['access_ttl'], 'user': _public_user(user)}


def logout(refresh_token: str) -> None:
    """Revoke the session identified by the refresh token."""
    if not refresh_token:
        raise AuthError(422, 'missing_refresh', 'Укажите refresh_token.')
    import hashlib
    provided_hash = hashlib.sha256(refresh_token.encode('ascii')).hexdigest()
    repository = auth_repository.AuthRepository()
    session = repository.find_session_by_hash(provided_hash)
    if session is not None and session['revoked_at'] is None:
        repository.revoke_session(session['id'])


def me(user_id: int) -> dict:
    return _public_user(_user_required(auth_repository.AuthRepository().find_by_id(user_id)))


# ------------------------------------------------------------------ seed admin

def seed_admin() -> dict:
    """Idempotently create or refresh the administrator account."""
    login, password = auth_crypto.admin_credentials()
    repository = auth_repository.AuthRepository()
    existing = repository.find_by_login(login)
    password_hash = hash_password(password)
    if existing is None:
        return repository.create_user(login, password_hash, 'Администратор', 'admin')
    changed = existing['role'] != 'admin' or not existing['is_active'] \
        or not verify_password(password, existing['password_hash']) \
        or existing['full_name'] != 'Администратор'
    if changed:
        repository.update_user(existing['id'], password_hash=password_hash,
                               full_name='Администратор', role='admin', is_active=True)
        return repository.find_by_id(existing['id'])
    return existing


# ------------------------------------------------------------------- users CRUD

def list_users() -> List[dict]:
    return [_public_user(row) for row in auth_repository.AuthRepository().list_users()]


def create_user(login: str, password: str, full_name: str, role: str) -> dict:
    login = (login or '').strip().lower()
    if not login or len(login) < 3:
        raise AuthError(422, 'invalid_login', 'Логин должен содержать не менее 3 символов.')
    if not password or len(password) < 6:
        raise AuthError(422, 'invalid_password', 'Пароль должен содержать не менее 6 символов.')
    if role not in USER_ROLES:
        raise AuthError(422, 'invalid_role', 'Роль должна быть admin, teacher или student.')
    if not (full_name or '').strip():
        raise AuthError(422, 'invalid_name', 'Укажите ФИО пользователя.')
    repository = auth_repository.AuthRepository()
    if repository.find_by_login(login) is not None:
        raise AuthError(409, 'login_exists', 'Пользователь с таким логином уже существует.')
    user = repository.create_user(login, hash_password(password), full_name.strip(), role)
    return _public_user(user)


def update_user(user_id: int, *, full_name: Optional[str] = None,
                role: Optional[str] = None, is_active: Optional[bool] = None,
                password: Optional[str] = None,
                display_name: Optional[str] = None) -> dict:
    repository = auth_repository.AuthRepository()
    existing = repository.find_by_id(user_id)
    if existing is None:
        raise AuthError(404, 'user_not_found', 'Пользователь не найден.')
    if role is not None and role not in USER_ROLES:
        raise AuthError(422, 'invalid_role', 'Роль должна быть admin, teacher или student.')
    if password is not None and len(password) < 6:
        raise AuthError(422, 'invalid_password', 'Пароль должен содержать не менее 6 символов.')
    if full_name is not None and not full_name.strip():
        raise AuthError(422, 'invalid_name', 'ФИО не может быть пустым.')
    if existing['role'] == 'admin' and is_active is False and repository.count_users() <= 1:
        raise AuthError(409, 'last_admin', 'Нельзя деактивировать последнего администратора.')
    updated = repository.update_user(
        user_id, full_name=full_name.strip() if full_name is not None else None,
        role=role, is_active=is_active,
        password_hash=hash_password(password) if password is not None else None,
        display_name=display_name)
    return _public_user(updated)


def delete_user(user_id: int) -> None:
    repository = auth_repository.AuthRepository()
    existing = repository.find_by_id(user_id)
    if existing is None:
        raise AuthError(404, 'user_not_found', 'Пользователь не найден.')
    if existing['role'] == 'admin' and repository.count_users() <= 1:
        raise AuthError(409, 'last_admin', 'Нельзя удалить последнего администратора.')
    repository.delete_user(user_id)


def reset_passwords(*, user_ids: Optional[List[int]] = None,
                    group_id: Optional[int] = None,
                    password: Optional[str] = None) -> List[dict]:
    if bool(user_ids) == (group_id is not None):
        raise AuthError(422, 'invalid_selection',
                        'Укажите список user_ids или group_id.')
    if password is not None and (not isinstance(password, str) or len(password) < 6):
        raise AuthError(422, 'invalid_password', 'Пароль должен содержать не менее 6 символов.')
    repository = auth_repository.AuthRepository()
    users = (repository.list_students_by_ids(user_ids) if user_ids is not None
             else repository.list_students_in_group(group_id))
    expected = set(int(value) for value in user_ids) if user_ids is not None else None
    if expected is not None and {int(user['id']) for user in users} != expected:
        raise AuthError(422, 'invalid_selection',
                        'Список должен содержать только существующих обучающихся.')
    if not users:
        raise AuthError(422, 'empty_selection', 'В выборке нет обучающихся.')
    credentials = []
    for user in users:
        temporary_password = password or __import__('secrets').token_urlsafe(9)
        repository.set_password(user['id'], hash_password(temporary_password))
        credentials.append({'user_id': user['id'], 'login': user['login'],
                            'display_name': user.get('display_name') or user['full_name'],
                            'password': temporary_password})
    return credentials


# ------------------------------------------------------------------ groups CRUD

def list_groups() -> List[dict]:
    return auth_repository.AuthRepository().list_groups()


def create_group(name: str, description: str = '',
                 teacher_id: Optional[int] = None) -> dict:
    name = (name or '').strip()
    if not name:
        raise AuthError(422, 'invalid_name', 'Укажите название группы.')
    repository = auth_repository.AuthRepository()
    if any(g['name'] == name for g in repository.list_groups()):
        raise AuthError(409, 'group_exists', 'Группа с таким названием уже существует.')
    if teacher_id is not None and repository.find_by_id(teacher_id) is None:
        raise AuthError(404, 'teacher_not_found', 'Преподаватель не найден.')
    return repository.create_group(name, description, teacher_id)


def update_group(group_id: int, name: Optional[str] = None,
                 description: Optional[str] = None,
                 teacher_id: Optional[int] = None) -> dict:
    repository = auth_repository.AuthRepository()
    group = repository.get_group(group_id)
    if group is None:
        raise AuthError(404, 'group_not_found', 'Группа не найдена.')
    if name is not None and not name.strip():
        raise AuthError(422, 'invalid_name', 'Название группы не может быть пустым.')
    if name is not None and any(g['id'] != group_id and g['name'] == name.strip() for g in repository.list_groups()):
        raise AuthError(409, 'group_exists', 'Группа с таким названием уже существует.')
    if teacher_id is not None and repository.find_by_id(teacher_id) is None:
        raise AuthError(404, 'teacher_not_found', 'Преподаватель не найден.')
    updated = repository.update_group(
        group_id, name=name.strip() if name is not None else None,
        description=description, teacher_id=teacher_id)
    return updated


def delete_group(group_id: int) -> None:
    repository = auth_repository.AuthRepository()
    if repository.get_group(group_id) is None:
        raise AuthError(404, 'group_not_found', 'Группа не найдена.')
    repository.delete_group(group_id)


def list_group_members(group_id: int) -> List[dict]:
    repository = auth_repository.AuthRepository()
    if repository.get_group(group_id) is None:
        raise AuthError(404, 'group_not_found', 'Группа не найдена.')
    return repository.list_group_members(group_id)


def add_group_member(group_id: int, user_id: int) -> None:
    repository = auth_repository.AuthRepository()
    if repository.get_group(group_id) is None:
        raise AuthError(404, 'group_not_found', 'Группа не найдена.')
    if repository.find_by_id(user_id) is None:
        raise AuthError(404, 'user_not_found', 'Пользователь не найден.')
    repository.add_group_member(group_id, user_id)


def remove_group_member(group_id: int, user_id: int) -> None:
    repository = auth_repository.AuthRepository()
    if repository.get_group(group_id) is None:
        raise AuthError(404, 'group_not_found', 'Группа не найдена.')
    repository.remove_group_member(group_id, user_id)