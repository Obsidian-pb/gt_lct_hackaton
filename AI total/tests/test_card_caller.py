import copy
import unittest
from card_fake import FactoryFake
from card_factory import generate, approve
from card_caller import ask, phone_evidence
from card_reference import generate as reference, validate_reference


class CallerTests(unittest.TestCase):
    def setUp(self):
        self.provider = FactoryFake()
        self.content = generate(self.provider, {})['content']
        self.content['fields']['phone_callback'] = ''
        self.scenario = {'version': 1, 'phone_callback': '+7 (000) 222-33-44'}
        self.request = {'content': self.content, 'caller_scenario': self.scenario}

    def test_hidden_phone_reference_and_approval_snapshot(self):
        ref = reference(self.provider, self.request)
        self.assertEqual(self.content['fields']['phone_callback'], '')
        self.assertNotIn(self.scenario['phone_callback'], self.content['report'])
        self.assertEqual(ref['answer']['expected_fields']['phone_callback'],
                         {'value': self.scenario['phone_callback'], 'evidence': phone_evidence(self.scenario)})
        approved = approve({**self.request, 'reference': ref, 'teacher': 'Тест', 'reference_checked': True})
        self.scenario['phone_callback'] = '+7 (000) 555-66-77'
        self.assertEqual(approved['reference']['source_scenario']['phone_callback'], '+7 (000) 222-33-44')
        with self.assertRaisesRegex(ValueError, 'изменены'):
            validate_reference(ref, self.content, self.scenario)

    def test_questions_do_not_fill_card_and_only_phone_question_reveals(self):
        before = copy.deepcopy(self.content)
        reply = ask(self.provider, {**self.request, 'question': 'Есть ли люди?'})
        self.assertFalse(reply['callback_disclosed'])
        self.assertNotIn(self.scenario['phone_callback'], reply['reply'])
        turns = [{'role': 'dispatcher', 'text': 'Есть ли люди?'}, {'role': 'caller', 'text': reply['reply']}]
        for question in ('Ваш телефон?', 'Куда перезвонить?', 'Можно по этому номеру?'):
            reply = ask(self.provider, {**self.request, 'question': question, 'turns': turns})
            self.assertTrue(reply['callback_disclosed'])
            self.assertIn(self.scenario['phone_callback'], reply['reply'])
        self.assertEqual(self.content, before)
        self.assertNotIn('fields', self.provider.calls[-1][1])
        self.assertNotIn('caller_scenario', self.provider.calls[-1][1])

    def test_failure_validation_and_fabricated_phone(self):
        with self.assertRaises(RuntimeError):
            ask(self.provider, {**self.request, 'question': 'FAIL'})
        for patch in ({'question': ''}, {'question': 'Да?', 'turns': [{'role':'caller','text':'secret'}]},
                      {'question':'Да?', 'caller_scenario':{'version':1,'phone_callback':'123'}}):
            with self.assertRaises(ValueError):
                ask(self.provider, {**self.request, **patch})
        class Bad:
            def generate(self, *args, **kwargs):
                return {'reply': 'Телефон +7 (999) 123-45-67', 'callback_requested': False}
        with self.assertRaisesRegex(ValueError, 'непроверенный'):
            ask(Bad(), {**self.request, 'question': 'Кто внутри?'})
