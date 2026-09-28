import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from ai_core import Engine
from ai_rest_server import make_server as make_ai_server
from application import dispatch
from card_fake import FactoryFake
import card_factory
import card_reference
from rest_api import RestAPI

TOKEN = 'integration-ai-rest-token-abcdefghijklmnopqrstuvwxyz'


class RemoteCallerProvider:
    model = 'remote-test-double'
    def __init__(self):
        self.calls = []

    def generate(self, system, payload, temperature=.3, schema=None):
        self.calls.append((system, payload, schema))
        if payload.get('operation') != 'learner_caller_reply':
            raise RuntimeError('unexpected remote operation')
        q = payload['question'].lower()
        if 'улиц' in q or 'адрес' in q or 'где' in q:
            street = payload['teacher_facts'].get('street', {}).get('value', '')
            house = payload['teacher_facts'].get('house', {}).get('value', '')
            return {'reply': ', '.join(x for x in (street, ('дом ' + house if house else '')) if x) or 'Не знаю.'}
        if 'пострад' in q:
            return {'reply': 'Не знаю.'}
        return {'reply': 'Не знаю.'}


class EndToEndGatewayTests(unittest.TestCase):
    def setUp(self):
        self.remote_provider = RemoteCallerProvider()
        self.ai_server = make_ai_server(self.remote_provider, 0, token=TOKEN)
        self.thread = threading.Thread(target=self.ai_server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.ai_server.shutdown); self.addCleanup(self.ai_server.server_close)
        self.env = patch.dict(os.environ, {
            'AI_DIALOGUE_REST_URL': f'http://127.0.0.1:{self.ai_server.server_port}',
            'AI_REST_TOKEN': TOKEN,
            'AI_DIALOGUE_REST_TIMEOUT': '5',
        }, clear=False); self.env.start(); self.addCleanup(self.env.stop)

        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.local_provider = FactoryFake()
        self.engine = Engine(self.local_provider, self.tmp.name)
        content = card_factory.generate(self.local_provider, {'topic':'Пожар','category':'fire'})['content']
        content['fields']['phone_aon'] = '+7 (000) 111-22-33'
        scenario = {'version':1, 'phone_callback':'+7 (000) 444-55-66'}
        ref = card_reference.generate(self.local_provider, {'content':content, 'caller_scenario':scenario})
        published = dispatch(self.engine, 'card_publish', {'content':content, 'reference':ref, 'caller_scenario':scenario,
            'teacher':'Преподаватель', 'reference_checked':True, 'opening':'Помогите, дым!'})
        self.expected_street = content['fields']['street']
        self.task_id = published['task_id']
        self.router = RestAPI(self.engine, threading.Lock())

    def test_browser_route_uses_current_fields_but_remote_teacher_truth(self):
        started = dispatch(self.engine, 'student_start', {'student':'Курсант', 'task_id':self.task_id, 'full_form':True})
        current = dict(started['card'])
        current['street'] = 'Сосновая'
        current['_report'] = 'Пострадавших нет'
        response = self.router.handle('POST', f"/api/v1/students/Курсант/sessions/{started['id']}/messages", {
            'question':'Подскажите улицу и что известно о пострадавших?',
            'source':'text', 'full_form':True, 'card':current,
        })
        self.assertIn(self.expected_street, response.data['history'][-1]['text'])
        sent = self.remote_provider.calls[-1][1]
        self.assertEqual(sent['student_fields']['street'], 'Сосновая')
        self.assertEqual(sent['student_fields']['_report'], 'Пострадавших нет')
        self.assertEqual(sent['teacher_facts']['street']['value'], self.expected_street)
        self.assertNotEqual(sent['teacher_facts']['street']['value'], sent['student_fields']['street'])
        public = json.dumps(response.data, ensure_ascii=False)
        self.assertNotIn('incident_source', public)
        self.assertNotIn(TOKEN, public)
        self.assertNotIn('+7 (000) 444-55-66', public)


if __name__ == '__main__':
    unittest.main()
