import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io
from contextlib import redirect_stdout
import urllib.error
import urllib.request

from ai_core import Engine, FIELDS
from voice import capture


class Fake:
    def __init__(self):
        self.calls = []
        self.response = {'reply': 'Не видела, чтобы он вышел.', 'hint': 'Уточните адрес.'}

    def generate(self, system, payload, temperature=.3, schema=None):
        self.calls.append(copy.deepcopy(payload))
        return copy.deepcopy(self.response)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.p = Fake()
        self.e = Engine(self.p, self.temp.name)
        self.t = self.e.sample()

    def start(self, level='medium'):
        self.t['level'] = level
        self.e.save(self.t)
        self.e.approve(self.t['id'], 'Преподаватель')
        return self.e.start(self.t['id'], 'Ученик')['id']

    def report(self):
        return {'summary': 'Предварительный разбор', 'fields': {key: {'verdict': 'partial', 'comment': 'Нужно уточнить',
                'clarification': 'Не спросил', 'evidence': []} for key in FIELDS}}

    def test_requires_approval_and_locks_reference(self):
        with self.assertRaises(ValueError):
            self.e.start(self.t['id'], 'Ученик')
        sid = self.start()
        with self.assertRaises(ValueError):
            self.e.edit_task(self.t['id'], 'address', 'expected', 'Другой адрес')
        original = self.e.load(self.t['id']); original['fields']['address']['expected'] = 'Подмена'; self.e.save(original)
        self.assertNotEqual(self.e.load(sid)['task']['fields']['address']['expected'], 'Подмена')

    def test_caller_never_receives_truth_or_reference(self):
        sid = self.start()
        self.e.ask(sid, 'Есть люди?', 'voice')
        payload = self.p.calls[-1]
        self.assertNotIn('truth', json.dumps(payload))
        self.assertNotIn('expected', json.dumps(payload))
        self.assertNotIn('Муж находится внутри гаража', json.dumps(payload, ensure_ascii=False))
        self.assertEqual(self.e.load(sid)['history'][-2]['source'], 'voice')
        view = self.e.student_view(sid)
        for key in ('task', 'assessment', 'reference_hash'):
            self.assertNotIn(key, view)

    def test_difficulty_and_hint_payload(self):
        sid = self.start('hard')
        with self.assertRaises(ValueError):
            self.e.hint(sid)
        self.assertEqual(self.p.calls, [])
        t = self.e.sample('easy'); self.e.approve(t['id'], 'Учитель')
        sid = self.e.start(t['id'], 'Ученик')['id']; self.e.hint(sid)
        self.assertNotIn('reference', self.p.calls[-1]); self.assertNotIn('known', self.p.calls[-1])
        self.assertEqual(len(self.e.load(sid)['hints']), 1)

    def test_submission_persists_on_ai_failure_and_freezes_card(self):
        sid = self.start(); self.e.set_field(sid, 'floors', '1'); self.e.submit(sid)
        self.p.response = {}
        with self.assertRaises(ValueError):
            self.e.assess(sid)
        self.assertEqual(Engine(self.p, self.temp.name).load(sid)['card']['floors'], '1')
        self.assertEqual(self.e.load(sid)['status'], 'submitted')
        with self.assertRaises(ValueError):
            self.e.set_field(sid, 'floors', '2')
        with self.assertRaises(ValueError):
            self.e.ask(sid, 'Ещё вопрос')

    def test_human_final_authority_and_citation_validation(self):
        sid = self.start(); self.e.ask(sid, 'Кто внутри?'); self.e.submit(sid)
        self.p.response = self.report()
        self.p.response['fields']['people']['evidence'] = [
            {'turn_id': 3, 'quote': 'Не видела, чтобы он вышел.'},
            {'turn_id': 2, 'quote': 'Кто внутри?'}, {'turn_id': 1, 'quote': 'Выдумка'}]
        report = self.e.assess(sid)
        self.assertEqual(len(report['fields']['people']['evidence']), 1)
        self.assertTrue(report['fields']['people']['citation_warning'])
        self.assertIsNone(self.e.student_view(sid)['result'])
        self.assertEqual(self.e.student_view(sid)['status'], 'pending_teacher')
        with self.assertRaises(ValueError):
            self.e.finalize(sid, 'Учитель', 5, 'Хорошо', {})
        choices = {key: {'decision': 'reject', 'comment': 'Мой вывод отличается от ИИ'} for key in FIELDS}
        self.e.finalize(sid, 'Учитель', 4, 'Итог преподавателя', choices)
        self.assertEqual(self.e.student_view(sid)['result']['grade'], 4)
        self.assertEqual(self.e.student_view(sid)['result']['fields']['people']['decision'], 'reject')

    def test_changed_session_reference_blocks_assessment(self):
        sid = self.start(); self.e.submit(sid)
        s = self.e.load(sid); s['task']['opening'] = 'Подмена'; self.e.save(s)
        with self.assertRaisesRegex(ValueError, 'Эталон изменён'):
            self.e.assess(sid)

    def test_missing_answer_is_not_appended(self):
        sid = self.start(); self.p.response = {'reply': ''}
        with self.assertRaises(ValueError):
            self.e.ask(sid, 'Адрес?')
        self.assertEqual(len(self.e.load(sid)['history']), 1)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.e.load('../config.local')

    def test_console_full_teacher_student_cycle(self):
        import console
        self.p.response = self.report() | {'reply': 'Муж заходил, но я не видела, чтобы он вышел.'}
        inputs = ['2', '1', '2', '2', 'Учитель', 'да', '5', '1', 'Ученик', 'Кто внутри?',
                  '/set people Возможно, муж внутри', '/finish', 'да', '4', '1', 'да',
                  *(['1'] * 7), 'Учитель', '4', 'Проверено мной', 'да', '6', 'Ученик', '1', '0']
        output = io.StringIO()
        with patch.object(console, 'GigaChat', return_value=self.p), patch('builtins.input', side_effect=inputs), \
             patch('sys.argv', ['console.py', '--data-dir', self.temp.name]), redirect_stdout(output):
            console.main()
        self.assertIn('Передано на проверку преподавателю.', output.getvalue())
        self.assertIn('Итог сохранён.', output.getvalue())
        self.assertIn('Оценка: 4', output.getvalue())
        session = self.e.list_items('s')[0]
        self.assertEqual(session['status'], 'reviewed')
        self.assertEqual(session['card']['people'], 'Возможно, муж внутри')

    def test_assignment_without_approved_tasks_does_not_create_session(self):
        with self.assertRaisesRegex(ValueError, 'Нет утверждённых карточек'):
            self.e.start_assigned('Ученик')
        self.assertEqual(self.e.list_items('s'), [])

    def test_only_approved_card_is_assigned_after_restart(self):
        self.e.approve(self.t['id'], 'Учитель')
        self.e.sample()  # A newer draft must not hide the approved card.
        restarted = Engine(self.p, self.temp.name)
        with patch('ai_core.random.choice') as choose_random:
            for _ in range(2):
                view = restarted.start_assigned('Ученик')
                session = restarted.load(view['id'])
                self.assertEqual(session['task']['id'], self.t['id'])
                self.assertTrue(all(value == '' for value in view['card'].values()))
                self.assertNotIn('task', view)
            choose_random.assert_not_called()

    def test_multiple_cards_randomly_assigned_only_from_approved(self):
        self.e.approve(self.t['id'], 'Учитель')
        another = self.e.sample()
        # The same Engine instance must notice approval of the new card.
        self.e.start_assigned('Первый ученик')
        self.e.approve(another['id'], 'Учитель')
        self.e.sample()  # Unapproved draft excluded from the random pool.
        assigned = set()
        for index in (0, -1):
            with patch('ai_core.random.choice', side_effect=lambda pool: pool[index]) as chooser:
                view = self.e.start_assigned('Другой ученик')
                pool = chooser.call_args.args[0]
                self.assertEqual({t['id'] for t in pool}, {self.t['id'], another['id']})
                assigned.add(self.e.load(view['id'])['task']['id'])
        self.assertEqual(assigned, {self.t['id'], another['id']})


class VoiceTests(unittest.TestCase):
    def test_bridge_delivers_only_confirmed_text_and_denies_bad_origin(self):
        def ready(url):
            with urllib.request.urlopen(url) as response:
                self.assertIn('Включить микрофон', response.read().decode())
            data = json.dumps({'text': 'Где вы находитесь?'}).encode()
            bad = urllib.request.Request(url, data=data, headers={'Origin': 'https://unrelated.example'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(bad)
            self.assertEqual(error.exception.code, 403)
            with urllib.request.urlopen(urllib.request.Request(url, data=data)) as response:
                self.assertEqual(response.status, 200)
        self.assertEqual(capture(timeout=2, open_browser=False, on_ready=ready), 'Где вы находитесь?')


if __name__ == '__main__':
    unittest.main()
