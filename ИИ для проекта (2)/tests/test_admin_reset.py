import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from ai_core import Engine
from web_ui import make_server


class FakeProvider:
    def complete(self, *args, **kwargs):
        return '{}'


class AdminResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token_path = Path(self.tmp.name) / 'admin-reset-token.txt'
        self.patch = patch('web_ui.ADMIN_RESET_TOKEN_PATH', self.token_path)
        self.patch.start()
        self.server = make_server(Engine(FakeProvider(), self.tmp.name), 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.patch.stop()
        self.tmp.cleanup()

    def _token(self):
        token = 'A' * 43
        self.token_path.write_text(token, encoding='ascii')
        return token

    def _post(self, token):
        request = urllib.request.Request(
            self.base + '/admin-reset/confirm',
            data=json.dumps({'token': token}).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/json', 'Origin': self.base},
        )
        return urllib.request.urlopen(request, timeout=3)

    def test_one_time_reset_page_and_confirmation(self):
        token = self._token()
        with urllib.request.urlopen(self.base + '/admin-reset?token=' + token, timeout=3) as response:
            page = response.read().decode('utf-8')
        self.assertIn('Сброс администратора', page)
        self.assertTrue(self.token_path.exists())

        with self._post(token) as response:
            payload = json.loads(response.read().decode('utf-8'))
        self.assertTrue(payload['ok'])
        self.assertFalse(self.token_path.exists())

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(token)
        self.assertEqual(ctx.exception.code, 403)

    def test_invalid_and_expired_tokens_are_rejected(self):
        token = self._token()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + '/admin-reset?token=' + ('B' * 43), timeout=3)
        self.assertEqual(ctx.exception.code, 403)

        old = time.time() - 700
        os.utime(self.token_path, (old, old))
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + '/admin-reset?token=' + token, timeout=3)
        self.assertEqual(ctx.exception.code, 403)
        self.assertFalse(self.token_path.exists())

    def test_confirmation_rejects_foreign_origin(self):
        token = self._token()
        request = urllib.request.Request(
            self.base + '/admin-reset/confirm',
            data=json.dumps({'token': token}).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/json', 'Origin': 'http://evil.example'},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(ctx.exception.code, 403)
        self.assertTrue(self.token_path.exists())


if __name__ == '__main__':
    unittest.main()
