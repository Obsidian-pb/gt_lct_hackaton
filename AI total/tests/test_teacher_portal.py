import tempfile
import unittest
from unittest.mock import Mock
from ai_core import Engine
from storage_adapter import StorageAdapter
from web_ui import dispatch
from test_core import Fake


class TeacherPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine(Fake(), self.temp.name)
        self.task = self.engine.sample('easy')
        self.payload = dict(plan_id='test-plan-123', title='Проверка', teacher='Тестов',
                            group='Группа 1', students=['А', 'Б'], task_ids=[self.task['id']],
                            seconds=300, mode='testing')

    def test_launch_validates_all_tasks_before_creation_and_retries_without_duplicates(self):
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'teacher_launch', self.payload)
        self.assertEqual(self.engine.list_items('s'), [])
        self.engine.approve(self.task['id'], 'Тестов')
        first = dispatch(self.engine, 'teacher_launch', self.payload)
        second = dispatch(self.engine, 'teacher_launch', self.payload)
        self.assertEqual(first, second)
        self.assertEqual(len(self.engine.list_items('s')), 2)
        own = dispatch(self.engine, 'student_overview', {'student': 'А'})
        self.assertEqual(len(own['sessions']), 1)
        self.assertNotIn('expected', str(own))
        with self.assertRaisesRegex(ValueError, 'тестирования'):
            self.engine.hint(first['session_ids'][0])

    def test_jwt_launch_keys_idempotency_by_user_id(self):
        self.engine.approve(self.task['id'], 'Тестов')
        storage = StorageAdapter(self.temp.name, mode='files')
        repository = Mock()
        repository.resolve_students.return_value = [11, 12]
        self.engine.storage = Mock(wraps=storage)
        self.engine.storage._repo = repository
        payload = {**self.payload, 'students': ['login11', 'login12'], '_owner_id': 7}
        first = dispatch(self.engine, 'teacher_launch', payload)
        for session_id in first['session_ids']:
            session = self.engine.load(session_id)
            session['student'] = 'Одно имя'
            self.engine.save(session)
        second = dispatch(self.engine, 'teacher_launch', payload)
        self.assertEqual(first, second)
        sessions = self.engine.list_items('s', teacher=7)
        self.assertEqual(len(sessions), 2)
        self.assertEqual({s['student_id'] for s in sessions}, {11, 12})
        self.assertEqual({s['student'] for s in sessions}, {'Одно имя'})
        repository.resolve_students.assert_called_with(['login11', 'login12'])

    def test_jwt_launch_rejects_aliases_for_same_student(self):
        self.engine.approve(self.task['id'], 'Тестов')
        storage = StorageAdapter(self.temp.name, mode='files')
        repository = Mock()
        repository.resolve_students.return_value = [11, 11]
        self.engine.storage = Mock(wraps=storage)
        self.engine.storage._repo = repository
        payload = {**self.payload, 'students': ['login11', 'alias11'], '_owner_id': 7}
        with self.assertRaisesRegex(ValueError, 'повторно'):
            dispatch(self.engine, 'teacher_launch', payload)
        self.assertEqual(self.engine.list_items('s'), [])

    def test_monitor_comment_and_finish_preserve_saved_card_and_separate_final_grade(self):
        self.engine.approve(self.task['id'], 'Тестов')
        sid = dispatch(self.engine, 'teacher_launch', self.payload)['session_ids'][0]
        self.engine.set_field(sid, 'address', 'Учебная, 12')
        dispatch(self.engine, 'teacher_note', {'id': sid, 'teacher': 'Тестов', 'comment': 'Уточнить'})
        rows = dispatch(self.engine, 'teacher_dashboard', {})['sessions']
        row = next(s for s in rows if s['id'] == sid)
        self.assertEqual(row['filled'], 1)
        self.assertIsNone(row['ai_remarks'])
        self.assertIsNone(row['grade'])
        self.assertEqual(row['comment'], 'Уточнить')
        dispatch(self.engine, 'teacher_finish', {'id': sid, 'teacher': 'Тестов', 'reason': 'Время занятия вышло'})
        s = self.engine.load(sid)
        self.assertEqual(s['status'], 'submitted')
        self.assertEqual(s['card']['address'], 'Учебная, 12')
        self.assertIsNone(s['teacher_decision'])
        with self.assertRaises(ValueError):
            self.engine.set_field(sid, 'address', 'Другой')
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'teacher_session', {'id': self.task['id']})

    def test_invalid_modes_names_and_timing_do_not_create_sessions(self):
        self.engine.approve(self.task['id'], 'Тестов')
        for change in ({'mode':'unknown'}, {'students':['']}, {'seconds':-1}, {'seconds':True},
                       {'task_ids':[self.task['id'],self.task['id']]}):
            with self.assertRaises(ValueError):
                dispatch(self.engine, 'teacher_launch', self.payload | change)
        self.assertEqual(self.engine.list_items('s'), [])
