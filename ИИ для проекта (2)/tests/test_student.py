import json
import tempfile
import unittest
from pathlib import Path
from ai_core import Engine, FIELDS
from web_ui import dispatch
from test_core import Fake


class StudentPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = Fake()
        self.engine = Engine(self.provider, self.temp.name)
        self.task = self.engine.sample('hard')

    def test_only_approved_tasks_and_own_sessions_no_hidden_data(self):
        self.assertEqual(dispatch(self.engine, 'student_overview', {'student': 'А'})['tasks'], [])
        self.engine.approve(self.task['id'], 'Учитель')
        self.engine.start(self.task['id'], 'Б')
        before = {p.name:p.read_bytes() for p in Path(self.temp.name).glob('*.json')}
        result = dispatch(self.engine, 'student_overview', {'student': 'А'})
        self.assertEqual(len(result['tasks']), 1)
        self.assertEqual(result['sessions'], [])
        self.assertNotIn('expected', json.dumps(result))
        self.assertNotIn('persona', json.dumps(result))
        self.assertEqual(before, {p.name:p.read_bytes() for p in Path(self.temp.name).glob('*.json')})

    def test_start_is_specific_idempotent_and_requires_approval(self):
        payload = {'student':'А', 'task_id':self.task['id']}
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'student_start', payload)
        self.engine.approve(self.task['id'], 'Учитель')
        first = dispatch(self.engine, 'student_start', payload)
        second = dispatch(self.engine, 'student_start', payload)
        self.assertEqual(first['id'], second['id'])
        self.assertIsNone(first['reference'])
        self.assertIsNone(first['result'])
        self.assertNotIn('task', first)
        for operation in ('review', 'assess', 'finalize'):
            with self.assertRaises(ValueError):
                dispatch(self.engine, 'student_action', {'student':'А', 'id':first['id'], 'operation':operation})
        with self.assertRaisesRegex(ValueError, 'другому'):
            dispatch(self.engine, 'student_action', {'student':'Б', 'id':first['id'], 'operation':'student'})

    def test_reference_only_after_teacher_review_and_submission_locks(self):
        self.engine.approve(self.task['id'], 'Учитель')
        s = dispatch(self.engine, 'student_start', {'student':'А','task_id':self.task['id']})
        req = {'student':'А','id':s['id']}
        card = {k:'Неизвестно' for k in FIELDS}
        view = dispatch(self.engine, 'student_action', {**req,'operation':'submit','card':card})
        self.assertEqual(view['card'],card)
        self.assertIsNone(view['reference'])
        self.assertIsNotNone(view['duration_seconds'])
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'student_action', {**req,'operation':'save_card','card':card})
        self.provider.response = {'summary':'Проверка', 'fields':{k:{'verdict':'partial','comment':'Уточнить','clarification':'Уточнить','evidence':[]} for k in FIELDS}}
        self.engine.assess(s['id'])
        self.assertIsNone(dispatch(self.engine,'student_action',{**req,'operation':'student'})['reference'])
        self.engine.finalize(s['id'],'Учитель',4,'Проверено',{k:{'decision':'agree','comment':'Хорошо'} for k in FIELDS})
        final = dispatch(self.engine,'student_action',{**req,'operation':'student'})
        self.assertEqual(final['result']['grade'],4)
        self.assertEqual(final['reference']['address'],self.task['fields']['address']['expected'])
        self.assertNotIn('assessment',final)
