import copy
import tempfile
import unittest
from ai_core import Engine, FIELDS
from dds import ACTION_LABELS


class Model:
    def __init__(self):
        self.calls = []

    def generate(self, system, payload, temperature=.3, schema=None):
        self.calls.append(copy.deepcopy(payload))
        if 'reference' in payload:
            return {'summary': 'Предварительный разбор', 'fields': {key: {
                'verdict': 'correct', 'comment': 'Проверить преподавателю', 'clarification': 'Учебное условие', 'evidence': []
            } for key in payload['field_labels']}}
        return {'reply': 'Повторите точный адрес.', 'hint': 'Сопоставьте карточку с уточнением от 112.'}


class DDSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.model = Model(); self.e = Engine(self.model, self.temp.name)
        self.t = self.e.sample('hard', 'dds'); self.e.approve(self.t['id'], 'Учитель')
        self.sid = self.e.start_assigned('Ученик', 'dds')['id']

    def test_two_modes_and_legacy_tasks_remain_distinct(self):
        t = self.e.sample(); t.pop('workflow'); self.e.save(t); self.e.approve(t['id'], 'Учитель')
        view = self.e.start_assigned('Другой ученик', 'caller')
        self.assertEqual(view['workflow'], 'caller'); self.assertIsNone(view['dds'])
        self.assertEqual(set(view['card'].values()), {''})
        self.assertEqual(len(self.e.approved_tasks('dds')), 1)
        self.assertEqual(len(self.e.approved_tasks('caller')), 1)

    def test_filled_card_and_available_evidence_without_gold(self):
        view = self.e.student_view(self.sid)
        self.assertEqual(view['card'], self.t['incoming_card'])
        self.assertIn('14', view['dds']['verification_notes'])
        self.assertNotIn('faults', view); self.assertNotIn('actions', view)
        self.assertNotIn('knowledge', view['dds'])

    def test_service_has_only_delivered_words_not_private_card(self):
        with self.assertRaises(ValueError): self.e.ask(self.sid, 'Адрес?')
        self.e.connect_service(self.sid)
        self.e.set_field(self.sid, 'address', 'СЕКРЕТНЫЙ ИСПРАВЛЕННЫЙ АДРЕС')
        self.e.ask(self.sid, 'Происшествие во дворе')
        p = self.model.calls[-1]
        self.assertNotIn('СЕКРЕТНЫЙ', str(p)); self.assertNotIn('incoming_card', p); self.assertNotIn('reference', p)
        self.assertEqual(p['delivered_message'], 'Происшествие во дворе')

    def test_drop_is_persisted_without_model_call_and_reconnect_does_not_reveal_it(self):
        self.e.connect_service(self.sid); self.e.ask(self.sid, 'Вода во дворе')
        self.e.set_channel(self.sid, 'drop'); before=len(self.model.calls)
        self.e.ask(self.sid, 'Адрес УТЕРЯННАЯУЛИЦА дом 987')
        self.assertEqual(len(self.model.calls), before)
        restarted=Engine(self.model, self.temp.name)
        self.assertEqual(restarted.student_view(self.sid)['dds']['connection'], 'disconnected')
        with self.assertRaises(ValueError): restarted.ask(self.sid, 'Вы слышите?')
        restarted.connect_service(self.sid); restarted.ask(self.sid, 'Что вы услышали?')
        p=self.model.calls[-1]
        self.assertNotIn('УТЕРЯННАЯУЛИЦА', str(p)); self.assertIn('Вода во дворе', str(p))
        self.assertEqual(p['attempt'], 2)

    def test_partial_message_does_not_reappear_in_next_turn(self):
        self.e.connect_service(self.sid); self.e.set_channel(self.sid, 'partial')
        self.e.ask(self.sid, 'Улица Лесная номер СЕКРЕТ')
        self.assertEqual(self.model.calls[-1]['delivered_message'], 'Улица Лесная')
        self.e.ask(self.sid, 'Подтвердите сообщение')
        self.assertNotIn('СЕКРЕТ', str(self.model.calls[-1]))
        row=next(r for r in self.e.load(self.sid)['history'] if r.get('delivery')=='partial')
        self.assertIn('СЕКРЕТ', row['text'])
        self.assertEqual(row['delivered'], 'Улица Лесная')

    def test_assessment_covers_actions_teacher_decides_and_no_drop_no_penalty(self):
        self.e.connect_service(self.sid); self.e.ask(self.sid, 'Вода во дворе')
        self.e.submit(self.sid); a=self.e.assess(self.sid)
        self.assertEqual(set(a['fields']), set(FIELDS)|set(ACTION_LABELS))
        self.assertEqual(a['fields']['action_recovery']['verdict'], 'unavailable')
        decisions={key:{'decision':'agree','comment':'Проверено'} for key in FIELDS}
        with self.assertRaises(ValueError): self.e.finalize(self.sid,'Учитель',4,'Хорошо',decisions)
        decisions.update({key:{'decision':'edit','comment':'Мой вывод'} for key in ACTION_LABELS})
        self.e.finalize(self.sid,'Учитель',4,'Хорошо',decisions)
        self.assertEqual(self.e.student_view(self.sid)['result']['grade'],4)

    def test_failed_model_does_not_consume_partial_transmission(self):
        self.e.connect_service(self.sid); self.e.set_channel(self.sid, 'partial')
        self.model.generate=lambda *args,**kwargs: (_ for _ in ()).throw(RuntimeError('API unavailable'))
        before=self.e.load(self.sid)['history']
        with self.assertRaises(RuntimeError): self.e.ask(self.sid,'Длинная фраза для передачи')
        self.assertEqual(self.e.load(self.sid)['history'],before)
        self.assertEqual(self.e.student_view(self.sid)['dds']['next_channel'],'partial')


if __name__ == '__main__': unittest.main()
