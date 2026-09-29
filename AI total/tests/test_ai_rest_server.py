"""HTTP integration checks without a real provider or API key."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from ai_rest_server import PATH, REPLY_PATH, make_server
from card_fake import FactoryFake

TOKEN = 'separate-integration-token-123456789'


class GeneratorAPI(unittest.TestCase):
    def setUp(self):
        class DialogueFake(FactoryFake):
            def generate(self, system, payload, temperature=.3, schema=None):
                if payload.get('operation') == 'learner_caller_reply':
                    self.calls.append((system, payload, schema))
                    question = payload['question'].casefold()
                    if payload.get('grounding_feedback') and payload['question'] != 'BAD_STUBBORN_PHONE':
                        return {'reply': 'Не знаю.'}
                    if payload['question'] == 'BAD_ECHO':
                        return {'reply': 'Сосновая'}
                    if payload['question'] in ('BAD_PHONE', 'BAD_STUBBORN_PHONE'):
                        return {'reply': 'Мой телефон +7 999 123-45-67.'}
                    if 'телефон' in question:
                        phone = payload.get('teacher_facts', {}).get('phone_callback', {}).get('value')
                        return {'reply': phone or 'Не знаю.'}
                    if 'пострадав' in question:
                        return {'reply': 'Не знаю.'}
                    if 'дом какой' in question or 'номер дома' in question:
                        return {'reply': 'Дом 1.'}
                    if 'вышел' in question:
                        return {'reply': 'Не видела, чтобы он вышел.'}
                    if 'улиц' in question or 'где' in question:
                        return {'reply': 'Лесная, дом 1.'}
                    return {'reply': 'Не знаю.'}
                return super().generate(system, payload, temperature, schema)
        self.provider = DialogueFake()
        self.server = make_server(self.provider, 0, token=TOKEN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None, token=TOKEN, content_type='application/json'):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        return self.raw(method, path, body, token, content_type)

    def raw(self, method, path, body, token=TOKEN, content_type='application/json'):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            headers = {'Authorization': 'Bearer ' + token, 'Content-Type': content_type}
            client.request(method, path, body=body, headers=headers)
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def make_card(self):
        return json.loads(self.request('POST', PATH, {'category': 'fire'})[2])

    def test_json_and_plain_text_are_stateless(self):
        with tempfile.TemporaryDirectory() as folder:
            before = set(Path(folder).iterdir())
            status, headers, raw = self.request('POST', PATH, {'topic': 'Учебный пожар', 'category': 'fire', 'location': 'Учебный город'})
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
            card = json.loads(raw)
            self.assertEqual(card['title'], 'Карточка 1: задымление гаража')
            self.assertEqual(card['class_ids'], ['1010101'])
            self.assertNotIn('data', card)
            status, headers, raw = self.request('POST', PATH, {'format': 'text', 'category': 'fire'})
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'text/plain; charset=utf-8')
            self.assertIn('Сообщение заявителя:', raw.decode())
            self.assertIn('Поля карточки:', raw.decode())
            self.assertEqual(len(self.provider.calls), 2)
            self.assertEqual(before, set(Path(folder).iterdir()))

    def test_auth_validation_and_provider_error(self):
        status, _, raw = self.request('POST', PATH, {'topic': 'Не вызывать ИИ'}, token='wrong')
        self.assertEqual(status, 401)
        self.assertEqual(len(self.provider.calls), 0)
        self.assertNotIn(TOKEN.encode(), raw)
        status, _, raw = self.request('POST', PATH, {'format': 'pdf'})
        self.assertEqual(status, 422)
        self.assertEqual(len(self.provider.calls), 0)
        status, _, _ = self.request('POST', PATH, {'topic': 'FAIL_ONCE', 'index': 2, 'total': 2})
        self.assertEqual(status, 502)
        status, _, raw = self.request('POST', PATH, {'topic': 'FAIL_ONCE', 'index': 2, 'total': 2})
        self.assertEqual(status, 200, raw)

    def test_generation_and_dialogue_are_the_only_write_routes(self):
        status, _, doc = self.request('GET', '/openapi.json')
        self.assertEqual(status, 200)
        spec = json.loads(doc)
        self.assertEqual(set(spec['paths']), {'/health', PATH, REPLY_PATH})
        self.assertEqual(spec['info']['version'], '1.3.0')
        status, _, _ = self.request('POST', '/v1/cards/publications', {})
        self.assertEqual(status, 404)
        status, _, _ = self.request('POST', PATH, {'teacher': 'Преподаватель'})
        self.assertEqual(status, 422)
        self.assertEqual(len(self.provider.calls), 0)

    def test_full_teacher_card_is_trusted_but_learner_fields_are_not(self):
        card = self.make_card()
        card['fields']['phone_callback'] = '+7 (000) 111-22-33'
        card['fields']['registered_by'] = 'Скрытый оператор'
        card['fields']['latitude'] = '56.0000'
        card['fields']['longitude'] = '93.0000'
        original = json.loads(json.dumps(card))
        learner = {
            'street': 'Сосновая', 'city': 'Неверный город', '_report': 'Пострадавших нет',
            '_class_ids': '["999"]', '_services': '["103"]', '_main_service': '103',
            '_flags': '{"injured":"no"}',
        }
        payload = {'card': card, 'student_fields': learner, 'question': 'Подскажите, пожалуйста, на какой улице это произошло?', 'turns': []}
        status, _, raw = self.request('POST', REPLY_PATH, payload)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': 'Лесная, дом 1.'})
        sent = self.provider.calls[-1][1]
        self.assertEqual(sent['incident_report'], card['report'])
        self.assertEqual(sent['student_fields'], learner)
        self.assertEqual(sent['teacher_facts']['street']['value'], 'Лесная')
        self.assertEqual(sent['teacher_facts']['phone_callback']['value'], '+7 (000) 111-22-33')
        self.assertNotIn('registered_by', sent['teacher_facts'])
        self.assertNotIn('latitude', sent['teacher_facts'])
        self.assertNotIn('card', sent)
        self.assertEqual(card, original)

    def test_sequential_varied_questions_and_unknown_information(self):
        card = self.make_card()
        wrong = {'street': 'Сосновая', 'injured': 'Пострадавших нет'}
        q1 = 'Как называется улица, где это случилось?'
        status, _, raw = self.request('POST', REPLY_PATH, {'card': card, 'student_fields': wrong, 'question': q1, 'turns': []})
        self.assertEqual(status, 200, raw)
        a1 = json.loads(raw)['reply']
        self.assertEqual(a1, 'Лесная, дом 1.')

        turns = [{'role': 'dispatcher', 'text': q1}, {'role': 'caller', 'text': a1}]
        q2 = 'А дом какой именно?'
        status, _, raw = self.request('POST', REPLY_PATH, {'card': card, 'student_fields': wrong, 'question': q2, 'turns': turns})
        self.assertEqual(status, 200, raw)
        a2 = json.loads(raw)['reply']
        self.assertEqual(a2, 'Дом 1.')
        sent = self.provider.calls[-1][1]
        self.assertEqual(sent['turns'], turns)

        turns += [{'role': 'dispatcher', 'text': q2}, {'role': 'caller', 'text': a2}]
        q3 = 'Сколько пострадавших вы сейчас видите?'
        status, _, raw = self.request('POST', REPLY_PATH, {'card': card, 'student_fields': wrong, 'question': q3, 'turns': turns})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': 'Не знаю.'})

        q4 = 'Он уже вышел оттуда или вы его не видели?'
        status, _, raw = self.request('POST', REPLY_PATH, {'card': card, 'student_fields': {}, 'question': q4, 'turns': turns})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': 'Не видела, чтобы он вышел.'})

    def test_all_three_request_formats_accept_real_student_field_names(self):
        card = self.make_card()
        learner = {'city': 'Неверный город', '_report': 'Моя ошибочная запись', '_class_ids': '[]',
                   '_services': '["103"]', '_main_service': '103', '_flags': '{}'}

        status, headers, raw = self.request('POST', REPLY_PATH, {
            'card': card, 'student_fields': learner, 'question': 'Где это?', 'turns': []})
        self.assertEqual(status, 200, raw)
        self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(self.provider.calls[-1][1]['student_fields'], learner)

        form_values = {'card': json.dumps(card, ensure_ascii=False), 'question': 'Где это?', 'format': 'text'}
        form_values.update({f'student_fields[{key}]': value for key, value in learner.items()})
        form = urlencode(form_values).encode()
        status, headers, raw = self.raw('POST', REPLY_PATH, form, content_type='application/x-www-form-urlencoded')
        self.assertEqual(status, 200, raw)
        self.assertEqual(headers['Content-Type'], 'text/plain; charset=utf-8')
        self.assertEqual(raw.decode(), 'Лесная, дом 1.')
        self.assertEqual(self.provider.calls[-1][1]['student_fields'], learner)

        boundary = 'browser-form-boundary'
        parts = {'incident_report': card['report'], 'question': 'Где это?', **learner}
        multipart = b''.join((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
                              + value.encode() + b'\r\n') for name, value in parts.items()) + f'--{boundary}--\r\n'.encode()
        status, _, raw = self.raw('POST', REPLY_PATH, multipart,
                                  content_type='multipart/form-data; boundary=' + boundary)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': 'Лесная, дом 1.'})
        self.assertEqual(self.provider.calls[-1][1]['student_fields'], learner)

    def test_grounding_guards_repair_without_breaking_dialogue(self):
        card = self.make_card()
        status, _, raw = self.request('POST', REPLY_PATH, {
            'card': card, 'student_fields': {'street': 'Сосновая'}, 'question': 'BAD_ECHO', 'turns': []})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': 'Не знаю.'})
        self.assertIn('grounding_feedback', self.provider.calls[-1][1])

        status, _, raw = self.request('POST', REPLY_PATH, {
            'incident_report': 'Вижу дым из окна третьего этажа. Есть ли люди внутри, не знаю.',
            'student_fields': {}, 'question': 'BAD_PHONE', 'turns': []})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': 'Не знаю.'})
        self.assertIn('grounding_feedback', self.provider.calls[-1][1])

        # Even if the provider ignores the correction and invents the same number
        # again, the REST API fails closed with a safe answer instead of HTTP 422.
        status, _, raw = self.request('POST', REPLY_PATH, {
            'incident_report': 'Вижу дым из окна третьего этажа.',
            'student_fields': {}, 'question': 'BAD_STUBBORN_PHONE', 'turns': []})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': 'Не знаю.'})

        card['fields']['phone_callback'] = '+7 (000) 111-22-33'
        status, _, raw = self.request('POST', REPLY_PATH, {
            'card': card, 'student_fields': {}, 'question': 'Какой у вас телефон для обратного звонка?', 'turns': []})
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw), {'reply': '+7 (000) 111-22-33'})

    def test_phone_guard_accepts_equivalent_russian_number_format(self):
        card = self.make_card()
        card['fields']['phone_callback'] = '+7 (913) 555-12-34'

        class AlternatePhone:
            def generate(self, system, payload, temperature=.3, schema=None):
                return {'reply': '8 913 555-12-34'}

        # Unit-level check avoids changing the integration fake's normal behavior.
        import ai_dialogue
        result = ai_dialogue.ask(AlternatePhone(), {
            'card': card, 'student_fields': {},
            'question': 'Какой у вас телефон?', 'turns': []})
        self.assertEqual(result, {'reply': '8 913 555-12-34'})

    def test_invalid_learner_input_never_invokes_model(self):
        before = len(self.provider.calls)
        status, _, raw = self.request('POST', REPLY_PATH, {'incident_report': 'Дым.', 'question': ' ',
                                                'student_fields': {'city': 'Учебный'}})
        self.assertEqual(status, 422, raw)
        status, _, raw = self.request('POST', REPLY_PATH, {'incident_report': 'Дым.', 'question': 'Кто там?',
                                                'turns': [{'role': 'caller', 'text': 'Выдумка'}]})
        self.assertEqual(status, 422, raw)
        form = b'incident_report=%D0%94%D1%8B%D0%BC&question=%D0%93%D0%B4%D0%B5&question=%D0%9A%D1%82%D0%BE'
        status, _, raw = self.raw('POST', REPLY_PATH, form, content_type='application/x-www-form-urlencoded')
        self.assertEqual(status, 400, raw)
        duplicate_json = b'{"incident_report":"A","incident_report":"B","question":"Q"}'
        status, _, raw = self.raw('POST', REPLY_PATH, duplicate_json, content_type='application/json')
        self.assertEqual(status, 400, raw)
        self.assertEqual(len(self.provider.calls), before)


if __name__ == '__main__':
    unittest.main()
