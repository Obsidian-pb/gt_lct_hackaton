"""HTTP contract and complete teacher/student flow; no real AI credentials."""
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.parse import quote
from unittest.mock import patch

from ai_core import Engine, FIELDS
from api_contract import ROUTES, openapi
from test_core import Fake
from web_ui import make_server

TOKEN = 'integration-test-token-only-123456789'


class RestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = Fake()
        self.engine = Engine(self.provider, self.temp.name)
        self.server = make_server(self.engine, 0, api_token=TOKEN, allowed_origins=['http://localhost:5173'], legacy_api=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.ui_token = re.search(r'name="ui-token" content="([^"]+)"', self.raw('GET','/')[2].decode())[1]

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2);self.temp.cleanup()

    def raw(self, method, target, body=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            client.request(method, target, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def call(self, method, target, data=None, status=200, **headers):
        auth = {'X-UI-Token': self.ui_token, **headers}
        body = None if data is None else json.dumps(data,ensure_ascii=False).encode()
        if body is not None: auth['Content-Type']='application/json'
        code, reply_headers, reply = self.raw(method, '/api/v1'+target, body, auth)
        parsed=json.loads(reply)
        self.assertEqual(code,status,parsed)
        self.assertEqual(parsed['request_id'],reply_headers['X-Request-ID'])
        return parsed,reply_headers

    def task(self):
        result, headers = self.call('POST','/tasks',{'level':'medium','sample':True},status=201)
        task=result['data']
        self.assertEqual(headers['Location'],'/api/v1/tasks/'+task['id'])
        return task

    def session(self):
        task=self.task()
        self.call('POST','/tasks/'+task['id']+'/approvals',{'teacher':'Преподаватель'})
        name='Иванов А. А.'
        base='/students/'+quote(name,safe='')
        result,_=self.call('POST',base+'/sessions',{'task_id':task['id']})
        return task, result['data'], base+'/sessions/'+result['data']['id']

    def test_complete_teacher_student_flow_with_safe_projections(self):
        task,s,path=self.session()
        self.assertNotIn('task',s);self.assertIsNone(s['reference'])
        before={p.name:p.read_bytes() for p in Path(self.temp.name).glob('*.json')}
        current,_=self.call('GET',path+'?full_form=false')
        self.assertEqual(current['data']['id'],s['id'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in Path(self.temp.name).glob('*.json')})
        self.provider.response={'reply':'Не знаю.'}
        reply,_=self.call('POST',path+'/messages',{'question':'Есть ли пострадавшие?'})
        self.assertEqual(reply['data']['history'][-1]['text'],'Не знаю.')
        card={key:'Неизвестно' for key in FIELDS}
        self.call('PUT',path+'/card',{'card':card})
        saved,_=self.call('POST',path+'/submissions',{'card':card})
        self.assertEqual(saved['data']['status'],'submitted');self.assertIsNone(saved['data']['reference'])
        self.call('PUT',path+'/card',{'card':card},status=409)
        self.provider.response={'summary':'Проверка','fields':{k:{'verdict':'partial','comment':'Уточнить','clarification':'Уточнить','evidence':[]} for k in FIELDS}}
        self.call('POST','/sessions/'+s['id']+'/assessments',{})
        teacher,_=self.call('GET','/teacher/sessions/'+s['id'])
        self.assertIn('task',teacher['data'])
        self.call('PUT','/works/'+s['id']+'/decision',{'teacher':'Преподаватель','grade':4,'conclusion':'Проверено','decisions':{k:{'decision':'agree','comment':'Проверено'} for k in FIELDS}})
        final,_=self.call('GET',path)
        self.assertEqual(final['data']['result']['grade'],4)
        self.assertEqual(final['data']['reference']['address'],task['fields']['address']['expected'])

    def test_get_does_not_create_task_and_put_updates_only_draft(self):
        task=self.task()
        self.call('PUT','/tasks/'+task['id'],{k:task[k] for k in ('title','opening','persona','fields')})
        self.call('POST','/tasks/'+task['id']+'/approvals',{'teacher':'Тест'})
        self.call('PUT','/tasks/'+task['id'],{k:task[k] for k in ('title','opening','persona','fields')},status=409)
        body,headers=self.call('GET','/tasks/generations',status=422)
        self.assertEqual(len(self.engine.list_items('t')),1)

    def test_student_cannot_access_other_student_projection(self):
        _,s,_=self.session()
        body,_=self.call('GET','/students/'+quote('Другой',safe='')+'/sessions/'+s['id'],status=403)
        self.assertEqual(body['error']['code'],'wrong_student')

    def test_authentication_and_bearer_are_separate_from_ai_key(self):
        code,_,raw=self.raw('GET','/api/v1/tasks')
        self.assertEqual(code,401)
        self.assertNotIn(TOKEN,raw.decode())
        code,_,raw=self.raw('GET','/api/v1/tasks',headers={'Authorization':'Bearer '+TOKEN})
        self.assertEqual(code,200);self.assertEqual(json.loads(raw)['data'],[])
        code,_,_=self.raw('GET','/api/v1/tasks',headers={'Authorization':'Bearer sk-aitunnel-fake'})
        self.assertEqual(code,401)

    def test_cross_origin_preflight_is_explicit_and_does_not_replace_auth(self):
        code,headers,body=self.raw('OPTIONS','/api/v1/tasks',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
        self.assertEqual(code,204);self.assertEqual(body,b'')
        self.assertEqual(headers['Access-Control-Allow-Origin'],'http://localhost:5173')
        code,_,_=self.raw('GET','/api/v1/tasks',headers={'Origin':'http://localhost:5173'})
        self.assertEqual(code,401)
        self.call('GET','/tasks',status=403,Origin='https://untrusted.invalid')
        code,_,_=self.raw('OPTIONS','/api/v1/tasks',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'DELETE'})
        self.assertEqual(code,403)

    def test_unknown_resource_and_wrong_method_have_distinct_statuses(self):
        self.call('GET','/unknown',status=404)
        self.call('GET','/tasks/t-000000000000',status=404)
        _,headers=self.call('DELETE','/tasks',status=405)
        self.assertIn('GET',headers['Allow']);self.assertIn('POST',headers['Allow'])
        self.call('GET','/tasks/../config.local.json',status=404)
        self.call('GET','/tasks/%2e%2e',status=422)

    def test_body_validation_does_not_write_data(self):
        for data in ({}, {'level': 'invalid'}, {'level':'medium','sample':'false'}, {'level':'medium','action':'approve'}, {'level':'medium','extra':'field'}):
            with self.subTest(data=data):
                expected=400 if 'action' in data else 422
                self.call('POST','/tasks',data,status=expected)
        for raw,status,content_type in [(b'{broken',400,'application/json'),(b'[]',400,'application/json'),(b'{}',415,'text/plain'),(b'x'*256001,413,'application/json'),(b'{"level":NaN}',400,'application/json')]:
            code,_,_=self.raw('POST','/api/v1/tasks',raw,{'X-UI-Token':self.ui_token,'Content-Type':content_type})
            self.assertEqual(code,status)
        self.assertEqual(self.engine.list_items('t'),[])

    def test_path_parameters_cannot_be_overridden_from_body(self):
        task=self.task()
        self.call('PUT','/tasks/'+task['id'],{'id':'t-000000000000','title':'test'},status=400)
        _,_,path=self.session()
        self.call('POST',path+'/messages',{'operation':'review','question':'hello'},status=400)

    def test_boolean_query_and_duplicate_parameters_are_checked(self):
        _,_,path=self.session()
        current,_=self.call('GET',path+'?full_form=false')
        self.assertEqual(set(current['data']['card']),set(FIELDS))
        self.call('GET',path+'?full_form=other',status=422)
        self.call('GET',path+'?full_form=false&full_form=true',status=400)
        self.call('GET',path+'?unknown=value',status=422)

    def test_geo_search_and_map_keep_original_coordinates(self):
        value,_=self.call('GET','/geo/addresses?q='+quote('Королева 7А')+'&limit=5')
        addresses=value['data']['addresses']
        self.assertTrue(any(x['house']=='7А' for x in addresses))
        self.assertLessEqual(len(addresses),5)
        geo,_=self.call('GET','/geo/map')
        self.assertEqual(geo['data']['city'],'Железногорск')
        self.assertGreater(len(geo['data']['roads']),100)

    def test_provider_failure_is_json_502_with_request_id(self):
        with patch('application.dispatch',side_effect=RuntimeError('not called')):
            with patch('rest_api.dispatch',side_effect=RuntimeError('ИИ: сервис недоступен')):
                result,_=self.call('POST','/ai/checks',{},status=502)
        self.assertEqual(result['error']['code'],'provider_error')
        self.assertIn('сервис недоступен',result['error']['message'])

    def test_training_assignment_is_idempotent(self):
        task=self.task()
        self.call('POST','/tasks/'+task['id']+'/approvals',{'teacher':'Тест'})
        payload={'plan_id':'test-plan-0001','title':'Пожары','teacher':'Тест','students':['А','Б'],'task_ids':[task['id']],'mode':'testing'}
        first,_=self.call('POST','/training-plans',payload)
        second,_=self.call('POST','/training-plans',payload)
        self.assertEqual(first['data'],second['data'])
        self.assertEqual(len(self.engine.list_items('s')),2)

    def test_openapi_matches_generated_file_and_every_route(self):
        code,_,raw=self.raw('GET','/api/v1/openapi.json')
        self.assertEqual(code,200)
        spec=json.loads(raw)
        self.assertEqual(spec,openapi())
        self.assertEqual(spec,json.loads((Path(__file__).resolve().parents[1]/'openapi.json').read_text()))
        operations=[v for path in spec['paths'].values() for v in path.values()]
        self.assertEqual(len(operations),len(ROUTES)+2)
        self.assertEqual(len({x['operationId'] for x in operations}),len(ROUTES)+2)
        self.assertNotIn(TOKEN,raw.decode());self.assertNotIn(self.ui_token,raw.decode())
        for r in ROUTES:
            op=spec['paths'][r.path][r.method.lower()]
            if r.method=='GET': self.assertNotIn('requestBody',op)

    def test_ui_and_legacy_pages_reference_rest_client(self):
        for path in ('/training','/scenarios'):
            code,_,body=self.raw('GET',path)
            self.assertEqual(code,200)
            self.assertIn(b'/api-client.js',body)
        code,_,body=self.raw('GET','/api/docs')
        self.assertEqual(code,200);self.assertIn(b'OpenAPI',body)
        code,_,_=self.raw('POST','/api',b'{}',{'X-UI-Token':self.ui_token,'Content-Type':'application/json'})
        self.assertEqual(code,410)

    def test_api_only_has_no_html_token_and_requires_integration_token(self):
        with self.assertRaises(ValueError): make_server(self.engine,0,api_only=True)
        other=make_server(self.engine,0,api_token=TOKEN,api_only=True)
        worker=threading.Thread(target=other.serve_forever,daemon=True);worker.start()
        client=http.client.HTTPConnection('127.0.0.1',other.server_port,timeout=5)
        try:
            client.request('GET','/')
            result=client.getresponse();self.assertEqual(result.status,404);self.assertNotIn(b'ui-token',result.read())
            client.request('GET','/api/v1/tasks',headers={'Authorization':'Bearer '+TOKEN})
            result=client.getresponse();self.assertEqual(result.status,200);result.read()
        finally:
            client.close();other.shutdown();other.server_close();worker.join(2)

    def test_head_and_health_have_no_ai_dependency(self):
        code,headers,body=self.raw('HEAD','/api/v1/health')
        self.assertEqual(code,200);self.assertEqual(body,b'')
        code,_,raw=self.raw('GET','/api/v1/health')
        self.assertEqual(code,200);self.assertEqual(json.loads(raw)['data']['status'],'ok')
        self.assertNotIn('root',json.loads(raw)['data'])
        self.assertEqual(self.engine.list_items('t'),[])


if __name__=='__main__': unittest.main()
