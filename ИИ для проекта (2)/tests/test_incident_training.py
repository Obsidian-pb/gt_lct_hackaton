import copy
import json
import tempfile
import unittest
from ai_core import Engine
from card_fake import FactoryFake
import card_factory
import card_reference
from web_ui import dispatch


class FullIncidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.provider = FactoryFake()
        self.engine = Engine(self.provider, self.tmp.name)
        content = card_factory.generate(self.provider, {'topic': 'Гараж', 'category': 'fire', 'index': 1, 'total': 1})['content']
        content['fields']['phone_aon'] = '+7 (000) 111-22-33'
        self.scenario = {'version': 1, 'phone_callback': '+7 (000) 444-55-66'}
        ref = card_reference.generate(self.provider, {'content': content, 'caller_scenario': self.scenario})
        self.request = {'content': content, 'reference': ref, 'caller_scenario': self.scenario,
                        'teacher': 'Учитель', 'reference_checked': True, 'opening': 'Помогите, дым!', 'level': 'hard'}

    def start(self):
        task = dispatch(self.engine, 'card_publish', self.request)
        return dispatch(self.engine, 'student_start', {'student': 'Ученик', 'task_id': task['task_id']})

    def test_publish_validation_idempotence_and_hidden_reference(self):
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'card_publish', {**self.request, 'reference_checked': False})
        first = dispatch(self.engine, 'card_publish', self.request)
        self.assertEqual(first, dispatch(self.engine, 'card_publish', self.request))
        self.assertEqual(len(self.engine.approved_tasks()), 1)
        s = self.start()
        self.assertEqual(s['format'], 'incident-v1')
        self.assertGreater(len(s['card']), 35)
        self.assertEqual(s['card']['house'], '')
        self.assertEqual(s['card']['phone_aon'], '+7 (000) 111-22-33')
        self.assertEqual(s['history'][0]['text'], 'Помогите, дым!')
        encoded = json.dumps(s, ensure_ascii=False)
        for secret in ('444-55-66', 'incident_source', 'incident_reference', 'known', 'expected', 'Муж заходил'):
            self.assertNotIn(secret, encoded)
        self.assertIsNone(s['reference'])

    def test_phone_gate_unknown_codes_failed_reply_and_submission_lock(self):
        s = self.start()
        req = {'student': 'Ученик', 'id': s['id']}
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'student_action', {**req, 'operation': 'save_card', 'card': {**s['card'], 'phone_callback': '+7 (000) 444-55-66'}})
        with self.assertRaises(RuntimeError):
            dispatch(self.engine, 'student_action', {**req, 'operation': 'ask', 'question': 'FAIL'})
        self.assertEqual(len(self.engine.load(s['id'])['history']), 1)
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'student_action', {**req, 'operation': 'hint'})
        s = dispatch(self.engine, 'student_action', {**req, 'operation': 'ask', 'question': 'Ваш телефон для перезвона?'})
        self.assertTrue(s['callback_disclosed'])
        self.assertIn('444-55-66', s['history'][-1]['text'])
        self.assertEqual(s['card']['phone_callback'], '')
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'student_action', {**req, 'operation': 'save_card', 'card': {**s['card'], '_class_ids': '["invented"]'}})
        card = {**s['card'], 'phone_callback': self.scenario['phone_callback'], 'house': '14'}
        submitted = dispatch(self.engine, 'student_action', {**req, 'operation': 'submit', 'card': card})
        self.assertEqual(submitted['card']['house'], '14')
        self.assertIsNone(submitted['reference'])
        with self.assertRaises(ValueError):
            dispatch(self.engine, 'student_action', {**req, 'operation': 'ask', 'question': 'Адрес?'})
        teacher = dispatch(self.engine, 'teacher_session', {'id': s['id']})
        self.assertIn('phone_callback', teacher['task']['fields'])
        self.assertIn('_services', teacher['task']['fields'])
        original = copy.deepcopy(teacher['task'])
        changed = {**self.request, 'opening': 'Другая вступительная реплика'}
        dispatch(self.engine, 'card_publish', changed)
        self.assertEqual(self.engine.load(s['id'])['task'], original)

    def test_legacy_full_form_keeps_original_reference_and_extra_notes(self):
        task = self.engine.sample()
        self.engine.approve(task['id'], 'Учитель')
        before = copy.deepcopy(self.engine.load(task['id']))
        s = dispatch(self.engine, 'student_start', {'student': 'Ученик', 'task_id': task['id'], 'full_form': True})
        self.assertEqual(s['format'], 'incident-v1')
        values = {**s['card'], 'address_text': 'Лесная, 14', 'street': 'Лесная', 'house': '14', 'apartment': '5'}
        req = {'student': 'Ученик', 'id': s['id'], 'full_form': True}
        saved = dispatch(self.engine, 'student_action', {**req, 'operation': 'save_card', 'card': values})
        self.assertEqual(saved['card']['apartment'], '5')
        self.assertEqual(self.engine.load(s['id'])['card']['address'], 'Лесная, 14')
        self.assertEqual(self.engine.load(s['id'])['task'], before)
        teacher = dispatch(self.engine, 'teacher_session', {'id': s['id']})
        self.assertEqual(teacher['incident_draft']['apartment'], '5')


if __name__ == '__main__':
    unittest.main()
