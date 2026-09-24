import tempfile
import unittest
from ai_core import Engine
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
