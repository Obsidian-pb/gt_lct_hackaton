import base64
import http.client
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from ai_core import Engine
from shared_auth import Accounts
from test_core import Fake
from web_ui import make_server


class SharedAccountAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.accounts=Accounts(self.temp.name)
        self.admin=self.accounts.create('admin','Администратор','admin','admin-password-123')
        self.student=self.accounts.create('student','Ученик Один','student','student-password-123')
        self.engine=Engine(Fake(),self.temp.name)
        self.server=make_server(self.engine,0,shared_server=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2); self.temp.cleanup()

    def request(self, method, path, login=None, password=None, data=None):
        headers={}
        if login:
            raw=base64.b64encode(f'{login}:{password}'.encode()).decode(); headers['Authorization']='Basic '+raw
        body=None if data is None else json.dumps(data,ensure_ascii=False).encode()
        if body is not None: headers['Content-Type']='application/json'
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            c.request(method,path,body,headers); r=c.getresponse(); raw=r.read()
            return r.status, json.loads(raw) if raw and r.getheader('Content-Type','').startswith('application/json') else raw
        finally: c.close()

    def test_last_active_admin_cannot_be_disabled_or_demoted(self):
        base='/api/v1/accounts/'+str(self.admin['id'])
        code,body=self.request('PATCH',base,'admin','admin-password-123',{'active':False})
        self.assertEqual(code,422,body)
        self.assertIn('последнего активного администратора',body['error']['message'])
        code,body=self.request('PATCH',base,'admin','admin-password-123',{'role':'student'})
        self.assertEqual(code,422,body)

    def test_admin_updates_role_disables_and_resets_password(self):
        base='/api/v1/accounts/'+str(self.student['id'])
        code,body=self.request('PATCH',base,'admin','admin-password-123',{'role':'teacher'})
        self.assertEqual(code,200,body); self.assertEqual(body['data']['role'],'teacher')
        code,body=self.request('PATCH',base,'admin','admin-password-123',{'active':False})
        self.assertEqual(code,200,body); self.assertFalse(body['data']['active'])
        self.assertEqual(self.request('GET','/api/v1/accounts/me','student','student-password-123')[0],401)
        self.request('PATCH',base,'admin','admin-password-123',{'active':True})
        code,body=self.request('POST',base+'/password','admin','admin-password-123',{'password':'new-password-456'})
        self.assertEqual(code,200,body)
        self.assertEqual(self.request('GET','/api/v1/accounts/me','student','student-password-123')[0],401)
        self.assertEqual(self.request('GET','/api/v1/accounts/me','student','new-password-456')[0],200)

    def test_self_registration_is_student_only_and_off_by_default(self):
        payload={'login':'newbie','full_name':'Новый Ученик','password':'newbie-password-123','role':'admin'}
        self.assertEqual(self.request('POST','/api/v1/accounts/register',data=payload)[0],403)
        with patch.dict(os.environ, {'ALLOW_SELF_REGISTRATION':'1'}):
            code,body=self.request('POST','/api/v1/accounts/register',data=payload)
        self.assertEqual(code,201,body); self.assertEqual(body['data']['role'],'student')

    def test_shared_admin_settings_round_trip(self):
        class SettingsStore:
            def __init__(self): self.values = {}
            def load_setting(self, key): return self.values.get(key)
            def save_setting(self, key, payload): self.values[key] = payload; return payload
        store = SettingsStore()
        self.engine.store = store
        code,body=self.request('GET','/api/v1/settings','admin','admin-password-123')
        self.assertEqual(code,200,body); self.assertEqual(body['data'],{})
        code,body=self.request('PUT','/api/v1/settings','admin','admin-password-123',{'system_name':'Стенд 112','timezone':'Asia/Krasnoyarsk'})
        self.assertEqual(code,200,body); self.assertEqual(body['data']['system_name'],'Стенд 112')
        code,_=self.request('GET','/api/v1/settings','student','student-password-123')
        self.assertEqual(code,403)

    def test_shared_workshop_round_trip_uses_server_store(self):
        class WorkshopStore:
            def __init__(self): self.state = None
            def load_workshop_state(self, user_id): return self.state
            def save_workshop_state(self, user_id, payload): self.state = payload; return payload
        store = WorkshopStore()
        self.engine.store = store
        code,body=self.request('GET','/api/v1/workshop','admin','admin-password-123')
        self.assertEqual(code,200,body); self.assertIsNone(body['data']['state'])
        state={'version':1,'cards':[],'selected':None,'batch':None,'teacher':'Администратор'}
        code,body=self.request('PUT','/api/v1/workshop','admin','admin-password-123',{'state':state})
        self.assertEqual(code,200,body); self.assertTrue(body['data']['saved'])
        code,body=self.request('GET','/api/v1/workshop','admin','admin-password-123')
        self.assertEqual(code,200,body); self.assertEqual(body['data']['state'],state)
        code,_=self.request('GET','/api/v1/workshop','student','student-password-123')
        self.assertEqual(code,403)

    def test_shared_pages_use_server_identity_instead_of_local_admin_password(self):
        code,body=self.request('GET','/','admin','admin-password-123')
        self.assertEqual(code,302)
        # request helper returns raw body only; check the target pages directly.
        code,body=self.request('GET','/admin-login','admin','admin-password-123')
        self.assertEqual(code,302)
        code,body=self.request('GET','/admin','admin','admin-password-123')
        self.assertEqual(code,200)
        text=body.decode('utf-8')
        self.assertIn('server-managed',text)
        self.assertIn('Администратор',text)
        code,body=self.request('GET','/student','student','student-password-123')
        self.assertEqual(code,200)
        self.assertIn('Ученик Один',body.decode('utf-8'))


if __name__=='__main__': unittest.main()
