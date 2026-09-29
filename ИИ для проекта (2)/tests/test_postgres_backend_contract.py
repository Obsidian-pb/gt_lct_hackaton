import copy
import tempfile
import unittest
from pathlib import Path

from ai_core import Engine, now
import curriculum
import materials
from shared_auth import Accounts
from database import MIGRATIONS, SCHEMA_VERSION
from test_core import Fake


class MemoryStore:
    def __init__(self):
        self.engine = {}
        self.curriculum = {}
        self.material_rows = []
        self.users = []
        self.saved_curriculum = 0

    def save_engine_item(self, item): self.engine[item['id']] = copy.deepcopy(item)
    def load_engine_item(self, identifier):
        if identifier not in self.engine: raise FileNotFoundError(identifier)
        return copy.deepcopy(self.engine[identifier])
    def engine_item_exists(self, identifier): return identifier in self.engine
    def list_engine_items(self, kind): return [copy.deepcopy(v) for k,v in self.engine.items() if k.startswith(kind+'-')]
    def save_curriculum(self, item): self.curriculum[item['id']] = copy.deepcopy(item); self.saved_curriculum += 1
    def load_curriculum(self, identifier):
        if identifier not in self.curriculum: raise FileNotFoundError(identifier)
        return copy.deepcopy(self.curriculum[identifier]
        )
    def list_curriculum(self, kind): return [copy.deepcopy(v) for k,v in self.curriculum.items() if k.startswith(kind+'-')]
    def delete_curriculum(self, identifier):
        if self.curriculum.pop(identifier, None) is None: raise FileNotFoundError(identifier)
    def list_materials(self): return copy.deepcopy(self.material_rows)
    def add_material(self, item): self.material_rows.append(copy.deepcopy(item)); return item
    def user_count(self): return len(self.users)
    def create_user(self, **kwargs):
        if any(x['login'] == kwargs['login'] or x['full_name'] == kwargs['full_name'] for x in self.users):
            raise ValueError('Логин или имя уже зарегистрированы.')
        row = {'id':len(self.users)+1,'login':kwargs['login'],'full_name':kwargs['full_name'],'role':kwargs['role'],
               'salt':kwargs['salt'],'password_hash':kwargs['password_hash'],'active':True,'created_at':kwargs['created_at']}
        self.users.append(row); return {k:v for k,v in row.items() if k not in ('salt','password_hash')}
    def get_user_by_login(self, login, active_only=True):
        return next((copy.deepcopy(x) for x in self.users if x['login']==login and (x['active'] or not active_only)), None)
    def list_users(self): return [{k:v for k,v in x.items() if k not in ('salt','password_hash')} for x in self.users]
    def update_user(self, user_id, **values):
        row = next(x for x in self.users if x['id']==user_id)
        for k,v in values.items():
            if v is not None: row[k]=v
        return {k:v for k,v in row.items() if k not in ('salt','password_hash')}
    def update_password(self, user_id, *, salt, password_hash):
        row = next(x for x in self.users if x['id']==user_id); row['salt']=salt; row['password_hash']=password_hash


class PostgreSQLBackendContractTests(unittest.TestCase):
    def test_schema_covers_shared_server_entities(self):
        sql = '\n'.join(text for _, text in MIGRATIONS)
        self.assertEqual(SCHEMA_VERSION, 5)
        for table in ('app_users','auth_sessions','engine_items','curriculum_resources','training_participants','training_cards',
                      'training_events','materials','scenario_tasks','training_scenarios','training_tasks','session_results',
                      'workshop_states','system_settings'):
            self.assertIn('CREATE TABLE IF NOT EXISTS '+table, sql)
        self.assertIn('jsonb', sql.lower())
        self.assertIn('ON DELETE CASCADE', sql)

    def test_engine_uses_database_store_instead_of_json_files(self):
        store = MemoryStore()
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(Fake(), directory, store=store)
            task = engine.sample()
            self.assertTrue(engine.exists(task['id']))
            self.assertEqual(engine.load(task['id'])['id'], task['id'])
            self.assertEqual(len(engine.list_items('t')), 1)
            self.assertEqual(list(Path(directory).glob('*.json')), [])

    def test_curriculum_and_materials_use_shared_store(self):
        store = MemoryStore()
        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(Fake(), directory, store=store)
            task = engine.sample(); engine.approve(task['id'], 'Преподаватель')
            scenario = curriculum.save_scenario(engine, {'title':'Сценарий','teacher':'Преподаватель','task_ids':[task['id']]})
            curriculum.approve_scenario(engine, scenario['id'], 'Преподаватель')
            training = curriculum.save_training(engine, {'title':'Занятие','teacher':'Преподаватель','scenario_ids':[scenario['id']]})
            self.assertEqual(curriculum.get(engine, training['id'])['title'], 'Занятие')
            self.assertGreater(store.saved_curriculum, 0)
            entry = materials.add(engine, {'title':'Методика','url':'https://example.org/doc','teacher':'Преподаватель'})
            self.assertEqual(materials.items(engine)[0]['id'], entry['id'])
            self.assertFalse((Path(directory)/'curriculum'/'materials.json').exists())

    def test_accounts_can_live_in_same_store_and_password_is_not_public(self):
        store = MemoryStore()
        with tempfile.TemporaryDirectory() as directory:
            accounts = Accounts(directory, store)
            created = accounts.create('ivanov','Иванов Иван','student','very-long-password')
            self.assertNotIn('password_hash', created)
            import base64
            auth = 'Basic ' + base64.b64encode('ivanov:very-long-password'.encode()).decode()
            self.assertEqual(accounts.authenticate(auth)['full_name'], 'Иванов Иван')
            accounts.update(created['id'], role='teacher')
            self.assertEqual(accounts.list_users()[0]['role'], 'teacher')
            self.assertFalse((Path(directory)/'accounts.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
