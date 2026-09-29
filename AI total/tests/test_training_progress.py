import tempfile
import unittest

from ai_core import Engine, FIELDS
from web_ui import dispatch
from test_core import Fake


class SequentialTrainingModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine(Fake(), self.temp.name)
        self.tasks = []
        for _ in range(3):
            task = self.engine.sample('medium')
            self.engine.approve(task['id'], 'Преподаватель')
            self.tasks.append(self.engine.load(task['id']))

    def launch(self, mode='training', count=3):
        return dispatch(self.engine, 'teacher_launch', {
            'plan_id': 'training-plan-123', 'scenario_id': 'scenario-fire-123',
            'title': 'Пожары', 'teacher': 'Преподаватель', 'group': '1 группа',
            'students': ['Курсант'], 'task_ids': [t['id'] for t in self.tasks[:count]],
            'seconds': 300, 'mode': mode,
        })

    def expected_card(self, task):
        return {key: task['fields'][key]['expected'] for key in FIELDS}

    def test_only_first_card_is_active_and_next_opens_automatically(self):
        result = self.launch('training', 3)
        sessions = [self.engine.load(sid) for sid in result['session_ids']]
        sessions.sort(key=lambda s: s['training']['card_index'])
        self.assertEqual([s['status'] for s in sessions], ['active', 'queued', 'queued'])
        self.assertEqual(sessions[0]['training']['mode'], 'training')
        self.assertEqual(sessions[0]['training']['coaching_delay_seconds'], 10)

        first = sessions[0]
        view = dispatch(self.engine, 'student_action', {
            'student': 'Курсант', 'id': first['id'], 'operation': 'submit',
            'card': self.expected_card(first['task']), 'full_form': False,
        })
        self.assertTrue(view['auto_advanced'])
        self.assertEqual(view['training']['card_index'], 2)
        self.assertEqual(view['status'], 'active')
        self.assertIsNone(view['adaptation'])

        second = self.engine.load(view['id'])
        next_view = dispatch(self.engine, 'student_action', {
            'student': 'Курсант', 'id': second['id'], 'operation': 'submit',
            'card': self.expected_card(second['task']), 'full_form': False,
        })
        self.assertTrue(next_view['auto_advanced'])
        self.assertEqual(next_view['training']['card_index'], 3)

    def test_training_reveals_one_reference_field_per_nudge(self):
        result = self.launch('training', 1)
        session = self.engine.load(result['session_ids'][0])
        view1 = dispatch(self.engine, 'student_action', {
            'student': 'Курсант', 'id': session['id'], 'operation': 'nudge', 'card': session['card'],
        })
        self.assertEqual(len(view1['training_reveals']), 1)
        first = view1['training_reveals'][0]
        self.assertIn(first['field'], session['task']['fields'])
        self.assertEqual(first['value'], session['task']['fields'][first['field']]['expected'])

        view2 = dispatch(self.engine, 'student_action', {
            'student': 'Курсант', 'id': session['id'], 'operation': 'nudge', 'card': session['card'],
        })
        self.assertEqual(len(view2['training_reveals']), 2)
        self.assertNotEqual(view2['training_reveals'][0]['field'], view2['training_reveals'][1]['field'])

    def test_testing_has_no_nudges_and_queued_card_is_locked(self):
        result = self.launch('testing', 2)
        first, second = sorted((self.engine.load(sid) for sid in result['session_ids']), key=lambda s: s['training']['card_index'])
        self.assertEqual(first['training']['coaching_delay_seconds'], 0)
        with self.assertRaisesRegex(ValueError, 'тестирования'):
            dispatch(self.engine, 'student_action', {'student': 'Курсант', 'id': first['id'], 'operation': 'nudge', 'card': first['card']})
        with self.assertRaisesRegex(ValueError, 'предыдущую карточку'):
            dispatch(self.engine, 'student_action', {'student': 'Курсант', 'id': second['id'], 'operation': 'student'})


if __name__ == '__main__':
    unittest.main()
