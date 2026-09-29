"""Independent browser identities share server data but cannot act for one another."""
import base64
import http.client
import json
import tempfile
import threading
import unittest
from urllib.parse import quote

from ai_core import Engine
from application import dispatch
import card_factory
import card_reference
from shared_auth import Accounts
from card_fake import FactoryFake
from web_ui import make_server


class SharedServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.accounts = Accounts(self.temp.name)
        for login, name, role in [('admin', 'Администратор', 'admin'),
                                  ('teacher', 'Преподаватель', 'teacher'),
                                  ('ivanov', 'Иванов Иван', 'student'),
                                  ('petrova', 'Петрова Мария', 'student')]:
            self.accounts.create(login, name, role, 'test-password-123')
        self.engine = Engine(FactoryFake(), self.temp.name)
        self.server = make_server(self.engine, 0, shared_server=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, login=None, data=None):
        headers = {}
        if login:
            credentials = base64.b64encode(f'{login}:test-password-123'.encode()).decode()
            headers['Authorization'] = 'Basic ' + credentials
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        if body is not None:
            headers['Content-Type'] = 'application/json'
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=8)
        try:
            conn.request(method, path, body, headers)
            response = conn.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), json.loads(raw) if raw and response.getheader('Content-Type', '').startswith('application/json') else raw
        finally:
            conn.close()

    def test_roles_and_shared_training_data(self):
        code, headers, _ = self.request('GET', '/teacher')
        self.assertEqual(code, 302)
        self.assertIn('/login?role=teacher', headers.get('Location',''))
        self.assertEqual(self.request('GET', '/teacher', 'ivanov')[0], 403)
        self.assertEqual(self.request('GET', '/teacher', 'teacher')[0], 200)

        base = '/api/v1'
        source = card_factory.generate(self.engine.provider, {'topic':'Учебный пожар','category':'fire'})['content']
        caller = {'version':1, 'phone_callback':'+7 (000) 444-55-66'}
        reference = card_reference.generate(self.engine.provider, {'content':source, 'caller_scenario':caller})
        task_id = dispatch(self.engine, 'card_publish', {'content':source, 'reference':reference,
            'caller_scenario':caller, 'teacher':'Преподаватель', 'reference_checked':True})['task_id']
        code, _, training = self.request('POST', base+'/trainings', 'teacher',
            {'title':'Общее занятие', 'teacher':'Преподаватель', 'task_ids':[task_id]})
        self.assertEqual(code, 201, training)
        tid = training['data']['id']

        self.assertEqual(self.request('GET', base+'/trainings/'+tid+'/lobby', 'ivanov')[0], 403)
        self.assertEqual(self.request('POST', base+'/trainings/'+tid+'/lobby/joins', 'ivanov', {'student':'Петрова Мария'})[0], 403)
        self.assertEqual(self.request('POST', base+'/trainings/'+tid+'/lobby/joins', 'ivanov', {'student':'Иванов Иван'})[0], 200)
        self.assertEqual(self.request('POST', base+'/trainings/'+tid+'/lobby/joins', 'petrova', {'student':'Петрова Мария'})[0], 200)
        code, _, lobby = self.request('GET', base+'/trainings/'+tid+'/lobby', 'ivanov')
        self.assertEqual(code, 200, lobby)
        self.assertEqual({p['student'] for p in lobby['data']['participants']}, {'Иванов Иван','Петрова Мария'})
        self.assertEqual(self.request('GET', base+'/students/'+quote('Петрова Мария'), 'ivanov')[0], 403)
        self.assertEqual(self.request('PUT', base+'/trainings/'+tid+'/lobby/participants/'+lobby['data']['participants'][0]['id'],
                                      'ivanov', {'teacher':'Преподаватель','role':'operator'})[0], 403)

    def test_admin_can_register_user_without_frontend_changes(self):
        base = '/api/v1/accounts'
        self.assertEqual(self.request('GET', base, 'teacher')[0], 403)
        code, _, result = self.request('POST', base, 'admin',
            {'login':'sidorov','full_name':'Сидоров Олег','role':'student','password':'long-password-123'})
        self.assertEqual(code, 201, result)
        self.assertNotIn('password', result['data'])
        self.assertEqual(self.request('GET', base+'/me', 'sidorov')[0], 401)  # wrong test password
        self.assertIn('sidorov', [x['login'] for x in self.request('GET', base, 'admin')[2]['data']])


if __name__ == '__main__':
    unittest.main()
