"""Unit tests for auth_crypto: PBKDF2 password hashing and JWT HS256."""
import base64
import hashlib
import json
import time
import unittest
from unittest.mock import patch

import auth_crypto
from auth_crypto import _b64, _unb64


class AuthConfigTests(unittest.TestCase):
    def test_roles_required_by_default_and_explicit_override(self):
        with patch.dict(auth_crypto.os.environ, {}, clear=True):
            with patch('auth_crypto._load_auth_section', return_value={}):
                self.assertTrue(auth_crypto.get_auth_config()['require_roles'])
            with patch('auth_crypto._load_auth_section', return_value={'require_roles': False}):
                self.assertFalse(auth_crypto.get_auth_config()['require_roles'])
                with patch.dict(auth_crypto.os.environ, {'REQUIRE_ROLES': 'true'}):
                    self.assertTrue(auth_crypto.get_auth_config()['require_roles'])
            with patch.dict(auth_crypto.os.environ, {'REQUIRE_ROLES': 'false'}):
                with patch('auth_crypto._load_auth_section', return_value={}):
                    self.assertFalse(auth_crypto.get_auth_config()['require_roles'])


class PasswordHashTests(unittest.TestCase):
    def test_roundtrip(self):
        stored = auth_crypto.hash_password('секрет-пароль-123')
        self.assertTrue(auth_crypto.verify_password('секрет-пароль-123', stored))
        self.assertFalse(auth_crypto.verify_password('другой-пароль', stored))

    def test_hash_format(self):
        stored = auth_crypto.hash_password('abc123')
        prefix, iterations, salt_b64, hash_b64 = stored.split('$')
        self.assertEqual(prefix, 'pbkdf2_sha256')
        self.assertEqual(int(iterations), auth_crypto.PBKDF2_ITERATIONS)
        # Salt/digest are urlsafe-base64 without padding; decode accordingly.
        self.assertEqual(len(_unb64(salt_b64)), auth_crypto.PBKDF2_SALT_BYTES)
        self.assertEqual(len(_unb64(hash_b64)), 32)

    def test_urlsafe_hash_roundtrip(self):
        """Regression: urlsafe '-' in salt/digest must survive verification.

        A salt of repeated 0xFE yields the urlsafe character '-' in every
        base64 group, which plain b64decode would silently drop.
        """
        import hashlib
        salt = bytes([0xFE]) * 16
        digest = hashlib.pbkdf2_hmac('sha256', 'known-pass'.encode('utf-8'), salt, 200000)
        stored = f'pbkdf2_sha256$200000${_b64(salt)}${_b64(digest)}'
        self.assertIn('-', stored)
        self.assertTrue(auth_crypto.verify_password('known-pass', stored))
        self.assertFalse(auth_crypto.verify_password('other-pass', stored))

    def test_unique_salts(self):
        a = auth_crypto.hash_password('same-password')
        b = auth_crypto.hash_password('same-password')
        self.assertNotEqual(a, b)

    def test_malformed_stored(self):
        for stored in ('', 'not-a-hash', 'md5$1$aa$bb', 'pbkdf2_sha256$999$!$!'):
            self.assertFalse(auth_crypto.verify_password('p', stored), stored)

    def test_low_iterations_rejected(self):
        stored = 'pbkdf2_sha256$10$c2FsdA$c2FsdA'
        self.assertFalse(auth_crypto.verify_password('p', stored))


class JwtTests(unittest.TestCase):
    def _valid_claims(self, **extra):
        now = int(time.time())
        return {'sub': '1', 'role': 'admin', 'iat': now, 'exp': now + 300, **extra}

    def test_roundtrip(self):
        token = auth_crypto.encode_jwt(self._valid_claims(), 'secret-key')
        claims = auth_crypto.decode_jwt(token, 'secret-key')
        self.assertEqual(claims['sub'], '1')
        self.assertEqual(claims['role'], 'admin')

    def test_wrong_secret(self):
        token = auth_crypto.encode_jwt({'sub': '1'}, 'secret-a')
        with self.assertRaises(auth_crypto.AuthCryptoError):
            auth_crypto.decode_jwt(token, 'secret-b')

    def test_tampered_payload(self):
        token = auth_crypto.encode_jwt({'sub': '1', 'role': 'student'}, 'secret-key')
        header, body, signature = token.split('.')
        payload = json.loads(_unb64(body))
        payload['role'] = 'admin'
        forged_body = _b64(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
        forged = f'{header}.{forged_body}.{signature}'
        with self.assertRaises(auth_crypto.AuthCryptoError):
            auth_crypto.decode_jwt(forged, 'secret-key')

    def test_malformed(self):
        with self.assertRaises(auth_crypto.AuthCryptoError):
            auth_crypto.decode_jwt('a.b', 'secret-key')
        with self.assertRaises(auth_crypto.AuthCryptoError):
            auth_crypto.decode_jwt('a.b.c.d', 'secret-key')

    def test_expired(self):
        now = int(time.time())
        token = auth_crypto.encode_jwt({'sub': '1', 'iat': now - 100, 'exp': now - 50}, 'secret-key')
        with self.assertRaises(auth_crypto.AuthCryptoError):
            auth_crypto.decode_jwt(token, 'secret-key')

    def test_max_age(self):
        now = int(time.time())
        token = auth_crypto.encode_jwt({'sub': '1', 'iat': now - 500, 'exp': now + 500}, 'secret-key')
        with self.assertRaises(auth_crypto.AuthCryptoError):
            auth_crypto.decode_jwt(token, 'secret-key', max_age=60)
        self.assertEqual(auth_crypto.decode_jwt(token, 'secret-key')['sub'], '1')

    def test_issue_access_token(self):
        token = auth_crypto.issue_access_token(7, 'ivan', 'teacher', 'secret-key', ttl=600)
        claims = auth_crypto.decode_jwt(token, 'secret-key')
        self.assertEqual(claims['sub'], '7')
        self.assertEqual(claims['login'], 'ivan')
        self.assertEqual(claims['role'], 'teacher')
        self.assertLessEqual(claims['exp'] - claims['iat'], 600)

    def test_refresh_token(self):
        raw, digest = auth_crypto.new_refresh_token()
        self.assertEqual(len(raw), 43)
        self.assertEqual(digest, hashlib.sha256(raw.encode('ascii')).hexdigest())


if __name__ == '__main__':
    unittest.main()