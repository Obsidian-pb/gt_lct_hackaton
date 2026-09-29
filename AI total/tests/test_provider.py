import json
import os
import time
import unittest
from unittest.mock import patch

from provider import AIProvider, ProviderHTTPError


class ProviderTests(unittest.TestCase):
    def provider(self):
        p = AIProvider.__new__(AIProvider)
        p.config = {}
        p.provider = 'gigachat'
        p.label = 'GigaChat'
        p.key = 'fake-key'
        p.requested_model = 'auto'
        p.model = 'auto'
        p.requested_scope = 'auto'
        p.scope = None
        p.base = 'https://example.invalid/v1'
        p.oauth = 'https://auth.invalid/oauth'
        p.token = ''
        p.expires = 0.0
        p._models = []
        return p

    def test_scope_auto_detects_non_personal_key_and_selects_available_model(self):
        p = self.provider()
        calls = []
        def request(url, data=None, headers=None, timeout=75):
            calls.append((url, data))
            if url == p.oauth:
                scope = data.decode().split('scope=', 1)[1]
                if scope != 'GIGACHAT_API_CORP':
                    raise ProviderHTTPError(401)
                return {'access_token': 'token', 'expires_at': time.time() + 1200}
            if url.endswith('/models'):
                return {'data': [{'id': 'Embedding'}, {'id': 'GigaChat-2-Max'}]}
            raise AssertionError(url)
        p._request = request
        status = p.status()
        self.assertEqual(status['state'], 'available')
        self.assertEqual(p.scope, 'GIGACHAT_API_CORP')
        self.assertEqual(p.model, 'GigaChat-2-Max')
        self.assertEqual(sum(1 for url, _ in calls if url == p.oauth), 3)

    def test_structured_output_falls_back_to_plain_json_once(self):
        p = self.provider()
        p.token = 'token'; p.expires = time.time() + 1200; p.model = 'AnyModel'; p.scope = 'GIGACHAT_API_PERS'
        bodies = []
        def request(url, data=None, headers=None, timeout=75):
            if url.endswith('/chat/completions'):
                body = json.loads(data)
                bodies.append(body)
                if 'response_format' in body:
                    raise ProviderHTTPError(400)
                return {'choices': [{'message': {'content': '{"ok": true}'}}]}
            raise AssertionError(url)
        p._request = request
        result = p.generate('system', {'x': 1}, schema={'type': 'object'})
        self.assertEqual(result, {'ok': True})
        self.assertEqual(len(bodies), 2)
        self.assertIn('response_format', bodies[0])
        self.assertNotIn('response_format', bodies[1])

    def test_environment_key_accepts_optional_basic_prefix(self):
        with patch.dict(os.environ, {'AI_AUTHORIZATION_KEY': '  Basic abc123  '}, clear=False):
            p = AIProvider()
        self.assertEqual(p.key, 'abc123')


if __name__ == '__main__':
    unittest.main()
