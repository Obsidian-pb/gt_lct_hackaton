"""Password hashing (PBKDF2-HMAC-SHA256) and JWT HS256 for the auth layer.

The project keeps zero third-party Python dependencies, so all cryptography is
built on the standard library: hashlib, hmac, secrets, base64 and json.
The module also owns the JWT secret (auto-generated in config.local.json under
the "auth" section, overridable via the JWT_SECRET environment variable).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent

PBKDF2_ITERATIONS = 200_000
PBKDF2_HASH_NAME = 'sha256'
PBKDF2_SALT_BYTES = 16
HASH_PREFIX = 'pbkdf2_sha256'

JWT_ALG = 'HS256'
JWT_TYP = 'JWT'

DEFAULT_ACCESS_TTL = 8 * 3600       # access token lifetime, seconds
DEFAULT_REFRESH_TTL = 30 * 24 * 3600  # refresh token lifetime, seconds

DEFAULT_ADMIN_LOGIN = 'admin'
DEFAULT_ADMIN_PASSWORD = 'admin123'


class AuthCryptoError(RuntimeError):
    """Invalid hash string, JWT or missing/invalid secret."""


# --------------------------------------------------------------- base64 helpers

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _unb64(text: str) -> bytes:
    padding = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _encode_part(obj: dict) -> str:
    return _b64(json.dumps(obj, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


# ------------------------------------------------------------- password hashing

def hash_password(password: str) -> str:
    """Hash a password: pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>."""
    if not isinstance(password, str):
        raise ValueError('Пароль должен быть строкой.')
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(PBKDF2_HASH_NAME, password.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return '$'.join((HASH_PREFIX, str(PBKDF2_ITERATIONS), _b64(salt), _b64(digest)))


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification of a password against a stored hash."""
    if not isinstance(stored, str):
        return False
    try:
        prefix, iterations, salt_b64, hash_b64 = stored.split('$')
        if prefix != HASH_PREFIX:
            return False
        # hash_password encodes with urlsafe base64; plain b64decode would
        # silently drop the urlsafe '-' characters and corrupt the bytes.
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
        count = int(iterations)
    except (ValueError, TypeError):
        return False
    if count < 1000:
        return False
    digest = hashlib.pbkdf2_hmac(PBKDF2_HASH_NAME, password.encode('utf-8'), salt, count)
    return hmac.compare_digest(digest, expected)


# ------------------------------------------------------------------------ JWT

def encode_jwt(claims: Dict[str, Any], secret: str) -> str:
    """Encode a JWT (HS256). Caller supplies iat/exp itself if needed."""
    signing_input = (_encode_part({'alg': JWT_ALG, 'typ': JWT_TYP}) + '.'
                     + _encode_part(claims)).encode('ascii')
    signature = _b64(hmac.new(secret.encode('utf-8'), signing_input, hashlib.sha256).digest())
    return signing_input.decode('ascii') + '.' + signature


def decode_jwt(token: str, secret: str, *, max_age: Optional[int] = None) -> Dict[str, Any]:
    """Verify a JWT signature and return its claims.

    Raises AuthCryptoError on a malformed token, a bad signature, an expired
    token (exp) or, when max_age is given, an iat older than max_age seconds.
    """
    parts = token.split('.')
    if len(parts) != 3:
        raise AuthCryptoError('Неверный формат JWT.')
    header_text, body_text, signature_text = parts
    try:
        provided = _unb64(signature_text)
    except (ValueError, TypeError):
        raise AuthCryptoError('Неверная подпись JWT.') from None
    signing_input = (header_text + '.' + body_text).encode('ascii')
    expected = hmac.new(secret.encode('utf-8'), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, provided):
        raise AuthCryptoError('Подпись JWT не подтверждена.')
    try:
        claims = json.loads(_unb64(body_text).decode('utf-8'))
    except (ValueError, TypeError, UnicodeDecodeError):
        raise AuthCryptoError('Не удалось разобрать полезную нагрузку JWT.') from None
    if not isinstance(claims, dict):
        raise AuthCryptoError('Полезная нагрузка JWT не является объектом.')
    now = int(time.time())
    exp = claims.get('exp')
    if not isinstance(exp, int) or exp <= now:
        raise AuthCryptoError('Срок действия токена истёк.')
    iat = claims.get('iat')
    if max_age is not None and (not isinstance(iat, int) or now - iat > max_age):
        raise AuthCryptoError('Токен слишком старый.')
    return claims


def issue_access_token(user_id: int, login: str, role: str, secret: str,
                       ttl: Optional[int] = None) -> str:
    """Build a signed access-token JWT for a user."""
    ttl = int(ttl or DEFAULT_ACCESS_TTL)
    now = int(time.time())
    claims = {'sub': str(user_id), 'login': login, 'role': role,
              'iat': now, 'exp': now + ttl}
    return encode_jwt(claims, secret)


def new_refresh_token() -> tuple:
    """Return (raw_refresh_token, sha256_hex_hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode('ascii')).hexdigest()


# -------------------------------------------------------------- auth settings

def _load_auth_section() -> dict:
    path = ROOT / 'config.local.json'
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    section = data.get('auth') if isinstance(data, dict) else None
    return dict(section) if isinstance(section, dict) else {}


def get_auth_config() -> Dict[str, object]:
    """Effective auth settings: defaults < config.local.json < env.

    Keys: access_ttl, refresh_ttl (seconds) and require_roles (bool, Этап 5:
    enforce JWT roles on every REST route instead of the legacy UI token).
    """
    config = {'access_ttl': DEFAULT_ACCESS_TTL, 'refresh_ttl': DEFAULT_REFRESH_TTL,
              'require_roles': False}
    for key in ('access_ttl', 'refresh_ttl'):
        env_value = os.environ.get('JWT_' + key.upper())
        if env_value:
            try:
                config[key] = int(env_value)
                continue
            except ValueError:
                pass
        value = _load_auth_section().get(key)
        if value is not None:
            try:
                config[key] = int(value)
            except (TypeError, ValueError):
                pass
    env_roles = os.environ.get('REQUIRE_ROLES', '').strip().lower()
    if env_roles:
        config['require_roles'] = env_roles in ('1', 'true', 'yes', 'да')
    else:
        value = _load_auth_section().get('require_roles')
        config['require_roles'] = (bool(value) if isinstance(value, bool)
                                   else str(value).strip().lower() in ('1', 'true', 'yes', 'да'))
    return config


def ensure_jwt_secret() -> str:
    """Return the JWT secret, generating and persisting it on first use.

    Priority: JWT_SECRET env var > "auth"."jwt_secret" in config.local.json.
    When neither exists, a random secret is written into config.local.json
    (which is never committed to the repository).
    """
    value = os.environ.get('JWT_SECRET')
    if value:
        return str(value)
    section = _load_auth_section()
    if section.get('jwt_secret'):
        return str(section['jwt_secret'])
    secret = secrets.token_urlsafe(48)
    path = ROOT / 'config.local.json'
    data = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    auth = dict(data.get('auth') or {})
    auth['jwt_secret'] = secret
    data['auth'] = auth
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return secret


def admin_credentials() -> tuple:
    """Return (login, password) for the seeded administrator.

    Priority: env vars ADMIN_LOGIN/ADMIN_PASSWORD > "auth" section in
    config.local.json > built-in defaults (admin / admin123).
    """
    section = _load_auth_section()
    login = os.environ.get('ADMIN_LOGIN') or section.get('admin_login') or DEFAULT_ADMIN_LOGIN
    password = os.environ.get('ADMIN_PASSWORD') or section.get('admin_password') or DEFAULT_ADMIN_PASSWORD
    return str(login), str(password)