import http.client
import json
import tempfile
import threading
import unittest

from ai_core import Engine
from shared_auth import Accounts
from test_core import Fake
from web_ui import make_server


class SharedLoginUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        accounts = Accounts(self.temp.name)
        self.admin = accounts.create('admin','Администратор','admin','admin-password-123')
        self.teacher = accounts.create('teacher1','Преподаватель Один','teacher','teacher-password-123')
        self.student = accounts.create('student1','Обучающийся Один','student','student-password-123')
        self.engine = Engine(Fake(), self.temp.name)
        self.server = make_server(self.engine, 0, shared_server=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2); self.temp.cleanup()

    def request(self, method, path, data=None, cookie=None):
        headers={}
        if cookie: headers['Cookie']=cookie
        body=None if data is None else json.dumps(data,ensure_ascii=False).encode()
        if body is not None: headers['Content-Type']='application/json'
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        try:
            c.request(method,path,body,headers); r=c.getresponse(); raw=r.read()
            payload=json.loads(raw) if raw and r.getheader('Content-Type','').startswith('application/json') else raw
            return r.status, dict(r.getheaders()), payload
        finally: c.close()

    def login(self, role, login, password):
        code,headers,body=self.request('POST','/api/v1/auth/login',{'role':role,'login':login,'password':password})
        self.assertEqual(code,200,body)
        return headers['Set-Cookie'].split(';',1)[0], body['data']

    def test_shared_root_keeps_original_welcome_and_loads_login_fields_script(self):
        code, _, page = self.request('GET', '/')
        self.assertEqual(code, 200)
        html = page.decode('utf-8')
        self.assertIn('/welcome.css', html)
        self.assertIn('/react/app.js', html)
        self.assertIn('/welcome-login.js', html)
        code, _, script = self.request('GET', '/welcome-login.js')
        self.assertEqual(code, 200)
        js = script.decode('utf-8')
        self.assertIn('Логин', js)
        self.assertIn('Пароль', js)
        self.assertIn('/api/v1/auth/login', js)
        self.assertIn('welcome-auth-fields', js)

    def test_teacher_and_student_login_use_server_accounts(self):
        self.assertEqual(self.request('GET','/teacher')[0],302)
        self.assertEqual(self.request('GET','/student')[0],302)
        self.assertEqual(self.request('GET','/login?role=teacher')[0],200)

        teacher_cookie,data=self.login('teacher','teacher1','teacher-password-123')
        self.assertEqual(data['user']['full_name'],'Преподаватель Один')
        self.assertEqual(data['home'],'/teacher')
        self.assertEqual(self.request('GET','/teacher',cookie=teacher_cookie)[0],200)
        self.assertEqual(self.request('GET','/student',cookie=teacher_cookie)[0],403)

        student_cookie,data=self.login('student','student1','student-password-123')
        self.assertEqual(data['home'],'/student')
        code,_,page=self.request('GET','/student',cookie=student_cookie)
        self.assertEqual(code,200)
        self.assertIn('Обучающийся Один',page.decode('utf-8'))

    def test_wrong_role_and_logout(self):
        code,_,body=self.request('POST','/api/v1/auth/login',{'role':'teacher','login':'student1','password':'student-password-123'})
        self.assertEqual(code,403,body)
        self.assertEqual(body['error']['code'],'wrong_role')
        cookie,_=self.login('student','student1','student-password-123')
        self.assertEqual(self.request('GET','/api/v1/auth/me',cookie=cookie)[0],200)
        code,headers,body=self.request('POST','/api/v1/auth/logout',{},cookie=cookie)
        self.assertEqual(code,200,body)
        self.assertIn('Max-Age=0',headers['Set-Cookie'])
        self.assertEqual(self.request('GET','/api/v1/auth/me',cookie=cookie)[0],401)

    def test_admin_can_create_teacher_and_student_with_passwords(self):
        admin_cookie,_=self.login('admin','admin','admin-password-123')
        code,_,body=self.request('POST','/api/v1/accounts',{
            'login':'teacher2','full_name':'Преподаватель Два','role':'teacher','password':'teacher2-password-123'
        },cookie=admin_cookie)
        self.assertEqual(code,201,body)
        code,_,body=self.request('POST','/api/v1/accounts',{
            'login':'student2','full_name':'Обучающийся Два','role':'student','password':'student2-password-123'
        },cookie=admin_cookie)
        self.assertEqual(code,201,body)
        self.assertEqual(self.request('POST','/api/v1/auth/login',{'role':'teacher','login':'teacher2','password':'teacher2-password-123'})[0],200)
        self.assertEqual(self.request('POST','/api/v1/auth/login',{'role':'student','login':'student2','password':'student2-password-123'})[0],200)

    def test_shipped_admin_bundle_contains_shared_account_password_form(self):
        admin_cookie,_=self.login('admin','admin','admin-password-123')
        code,_,script=self.request('GET','/react/app.js',cookie=admin_cookie)
        self.assertEqual(code,200)
        bundled=script.decode('utf-8')
        def escaped(text):
            return ''.join(f'\\u{ord(char):04X}' if ord(char)>127 else char for char in text)
        self.assertIn('/api/v1/accounts',bundled)
        self.assertIn(escaped('Временный пароль'),bundled)
        self.assertIn(escaped('Сбросить пароль'),bundled)


if __name__=='__main__': unittest.main()
