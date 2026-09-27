"""Provider boundary tests use synthetic keys and never call a real paid API."""
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch

from provider import AIProvider, NoCredentialRedirect, ProviderHTTPError

SCHEMA = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok'], 'additionalProperties': False}
REPLY = {'choices': [{'message': {'content': '{"ok":true}'}}]}


class MultiProviderTests(unittest.TestCase):
    def make(self, **config):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'config.local.json'
        path.write_text(json.dumps({'authorization_key': 'fake-key', **config}), encoding='utf-8-sig')
        with patch.dict(os.environ, {'AI_PROJECT_CONFIG': str(path)}, clear=True):
            p = AIProvider()
        p._request = Mock(side_effect=AssertionError('Unexpected network request'))
        return p

    def test_openai_key_is_never_sent_to_gigachat_and_uses_openai_schema(self):
        p = self.make(authorization_key='Bearer sk-proj-fake-test', model='auto')
        calls = []
        def request(url, data=None, headers=None, **kwargs):
            calls.append(url)
            self.assertEqual(headers['Authorization'], 'Bearer sk-proj-fake-test')
            self.assertNotIn('RqUID', headers)
            if url.endswith('/models'):
                return {'data': [{'id': 'text-embedding-3-small'}, {'id': 'gpt-4o-mini'}]}
            self.assertEqual(url, 'https://api.openai.com/v1/chat/completions')
            body = json.loads(data)
            self.assertEqual(body['response_format']['json_schema'], {'name': 'training_response', 'schema': SCHEMA, 'strict': True})
            self.assertIn('max_completion_tokens', body)
            self.assertNotIn('max_tokens', body)
            self.assertEqual(body['model'], 'gpt-4o-mini')
            return REPLY
        p._request.side_effect = request
        self.assertEqual(p.generate('Тренировка', {'ученик': 'тест'}, schema=SCHEMA), {'ok': True})
        self.assertEqual(calls, ['https://api.openai.com/v1/models', 'https://api.openai.com/v1/chat/completions'])

    def test_legacy_openai_key_drops_stale_gigachat_model(self):
        p = self.make(authorization_key='sk-proj-fake', model='GigaChat-2-Pro')
        self.assertEqual(p.provider, 'openai')
        self.assertEqual(p.requested_model, 'auto')

    def test_explicit_model_does_not_require_models_permission_or_silently_change(self):
        p = self.make(provider='openai', model='my-model-alias')
        p._request.side_effect = None
        p._request.return_value = REPLY
        p.generate('system', {})
        self.assertEqual(p._request.call_count, 1)
        self.assertEqual(json.loads(p._request.call_args.args[1])['model'], 'my-model-alias')
        p._request.side_effect = ProviderHTTPError(404, 'model_not_found')
        with self.assertRaisesRegex(RuntimeError, 'не найдены модель'):
            p.generate('system', {})
        self.assertEqual(p.model, 'my-model-alias')

    def test_gemini_uses_compatible_endpoint_and_bearer(self):
        p = self.make(provider='gemini', authorization_key='AIza-fake', model='gemini-test-flash')
        p._request.side_effect = None
        p._request.return_value = REPLY
        self.assertEqual(p.generate('system', {}), {'ok': True})
        url, _, headers = p._request.call_args.args
        self.assertEqual(url, 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions')
        self.assertEqual(headers['Authorization'], 'Bearer AIza-fake')

    def test_claude_uses_native_messages_api_and_extracts_text_blocks(self):
        p = self.make(provider='anthropic', authorization_key='sk-ant-fake', model='claude-test')
        p._request.side_effect = None
        p._request.return_value = {'content': [{'type': 'thinking', 'thinking': 'private'}, {'type': 'text', 'text': '{"ok":true}'}]}
        self.assertEqual(p.generate('system', {}, schema=SCHEMA), {'ok': True})
        url, data, headers = p._request.call_args.args
        self.assertEqual(url, 'https://api.anthropic.com/v1/messages')
        self.assertEqual(headers['x-api-key'], 'sk-ant-fake')
        self.assertEqual(headers['anthropic-version'], '2023-06-01')
        self.assertNotIn('Authorization', headers)
        body = json.loads(data)
        self.assertIn('JSON Schema', body['system'])
        self.assertNotIn('response_format', body)
        self.assertEqual([m['role'] for m in body['messages']], ['user'])

    def test_compatible_service_accepts_opaque_key_and_exact_url_model(self):
        p = self.make(provider='openai_compatible', authorization_key='my.vendor:key.123', base_url='https://gateway.example.invalid/api/v1/', model='vendor/model')
        p._request.side_effect = None
        p._request.return_value = REPLY
        p.generate('system', {})
        url, data, headers = p._request.call_args.args
        self.assertEqual(url, 'https://gateway.example.invalid/api/v1/chat/completions')
        self.assertEqual(json.loads(data)['model'], 'vendor/model')
        self.assertEqual(headers['Authorization'], 'Bearer my.vendor:key.123')

    def test_compatible_without_models_endpoint_is_not_falsely_marked_available(self):
        p = self.make(provider='openai_compatible', base_url='https://gateway.example.invalid/v1', model='custom')
        p._request.side_effect = ProviderHTTPError(404)
        self.assertEqual(p.status()['state'], 'configured')

    def test_status_checks_api_even_for_explicit_model_without_generation(self):
        p = self.make(provider='openai', model='gpt-4o-mini')
        p._request.side_effect = None
        p._request.return_value = {'data': [{'id': 'gpt-4o-mini'}]}
        status = p.status()
        self.assertEqual(status['state'], 'available')
        self.assertIn('Генерация и квота ещё не проверены', status['message'])
        self.assertEqual(p._request.call_args.args, ('https://api.openai.com/v1/models',))
        self.assertNotIn('fake-key', json.dumps(status))

    def test_auth_and_rate_errors_are_distinct_and_not_retried(self):
        for code, message, status in [(None, 'ключ API не принят', 401), (None, 'доступ запрещён', 403), ('insufficient_quota', 'исчерпана квота', 429), (None, 'временная ошибка', 503)]:
            with self.subTest(status=status):
                p = self.make(provider='openai', model='gpt-4o-mini')
                p._request.side_effect = ProviderHTTPError(status, code)
                with self.assertRaisesRegex(RuntimeError, message):
                    p.generate('system', {}, schema=SCHEMA)
                self.assertEqual(p._request.call_count, 1)

    def test_schema_fallback_keeps_contract_and_stays_at_same_endpoint(self):
        p = self.make(provider='openai', model='gpt-4o-mini')
        p._request.side_effect = [ProviderHTTPError(400, param='response_format'), REPLY]
        self.assertEqual(p.generate('system', {}, schema=SCHEMA), {'ok': True})
        first, second = p._request.call_args_list
        self.assertEqual(first.args[0], second.args[0])
        self.assertIn('response_format', json.loads(first.args[1]))
        body = json.loads(second.args[1])
        self.assertNotIn('response_format', body)
        self.assertIn('JSON Schema', body['messages'][0]['content'])

    def test_reasoning_model_omits_temperature_and_keeps_completion_limit(self):
        p = self.make(provider='openai', model='o3-mini')
        p._request.side_effect = None
        p._request.return_value = REPLY
        p.generate('system', {})
        body = json.loads(p._request.call_args.args[1])
        self.assertNotIn('temperature', body)
        self.assertEqual(body['max_completion_tokens'], 4500)

    def test_bad_json_refusals_and_truncated_output_are_not_accepted(self):
        for message, reason in [({'content': None}, None), ({'content': '[1,2]'}, None), ({'content': 'prefix {"ok":true} junk'}, None), ({'content': '{"ok":true}'}, 'length'), ({'content': None, 'refusal': 'No'}, None)]:
            with self.subTest(message=message):
                p = self.make(provider='openai', model='gpt-4o-mini')
                p._request.side_effect = None
                p._request.return_value = {'choices': [{'message': message, 'finish_reason': reason}]}
                with self.assertRaises(RuntimeError):
                    p.generate('system', {})
        p._request.return_value = {'choices': [{'message': {'content': '```json\n{"ok":true}\n```'}}]}
        self.assertEqual(p.generate('system', {}), {'ok': True})

    def test_invalid_settings_fail_before_network_and_do_not_echo_key(self):
        for settings in [dict(provider='unknown'), dict(provider='openai_compatible'), dict(provider='openai_compatible', base_url='http://example.invalid', model='text'), dict(provider='openai_compatible', base_url='https://example.invalid/?key=fake-key', model='text'), dict(provider='openai', base_url='https://example.invalid/v1'), dict(authorization_key='sk-ambiguous-fake'), dict(authorization_key='bad\nkey')]:
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError) as raised:
                    self.make(**settings)
                self.assertNotIn('fake-key', str(raised.exception))

    def test_mismatched_gigachat_key_is_not_sent(self):
        p = self.make(provider='gigachat', authorization_key='sk-proj-fake')
        with self.assertRaisesRegex(RuntimeError, 'выбран GigaChat'):
            p.status()
        p._request.assert_not_called()

    def test_arbitrary_models_are_not_auto_selected(self):
        p = self.make(provider='openai')
        p._request.side_effect = None
        p._request.return_value = {'data': [{'id': 'embedding'}, {'id': 'expensive-unknown'}]}
        with self.assertRaisesRegex(RuntimeError, 'Укажите доступную текстовую модель'):
            p.generate('system', {})

    def test_error_body_is_sanitized_and_tls_stays_enabled(self):
        p = self.make(provider='openai', model='gpt-4o-mini')
        self.assertEqual(p.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(p.context.check_hostname)
        p.opener = Mock()
        body = json.dumps({'error': {'code': 'insufficient_quota', 'message': 'fake-secret prompt', 'param': 'fake-secret'}}).encode()
        p.opener.open.side_effect = urllib.error.HTTPError(p.base, 429, 'Error', {}, io.BytesIO(body))
        with self.assertRaises(ProviderHTTPError) as caught:
            AIProvider._request(p, p.base)
        error = caught.exception
        self.assertEqual(error.code, 'insufficient_quota')
        self.assertIsNone(error.param)
        self.assertNotIn('fake-secret', str(error.__dict__))

    def test_redirect_does_not_forward_credentials(self):
        request = urllib.request.Request('https://api.openai.com/v1/models', headers={'Authorization': 'Bearer fake'})
        handler = NoCredentialRedirect()
        self.assertIsNone(handler.redirect_request(request, None, 302, 'Moved', {}, 'https://other.invalid'))


if __name__ == '__main__':
    unittest.main()
