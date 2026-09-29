"""Unit tests for storage_documents: pure document<->row round trips.

No database is required: DB row tuples are simulated exactly as the Simple
Query protocol returns them (JSONB as JSON text, booleans as 't'/'f').
"""
from __future__ import annotations

import json
import unittest

import storage_documents as docs
import storage_repository as repo
from storage_documents import load_ts

FIELDS = {'address': 'Адрес', 'incident': 'Что произошло', 'people': 'Люди внутри',
          'injured': 'Пострадавшие', 'floors': 'Этажность', 'entrance': 'Подъезд / вход',
          'access': 'Как проехать'}

NAMES = {'Учитель': 1, 'Студент': 2}


def resolve(name, kind):
    if name is None:
        return None
    return NAMES[name]


def name_of(user_id):
    if user_id is None:
        return None
    for name, uid in NAMES.items():
        if uid == int(user_id):
            return name
    return None


def row_dict(columns, row):
    """Simulate a PostgreSQL row as dicts: JSONB -> text, bool -> t/f."""
    result = {}
    for column, value in zip(columns, row):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            value = 't' if value else 'f'
        result[column] = value
    return result


def make_fields(prefix=''):
    return {key: {'truth': f'{prefix}{key} truth', 'known': f'{prefix}{key} known',
                  'expected': f'{prefix}{key} expected', 'criterion': 'Критерий',
                  'weight': 3} for key in FIELDS}


def base_task(**overrides):
    task = {
        'id': 't-1234567890ab', 'title': 'Пожар в квартире', 'status': 'approved',
        'workflow': 'caller', 'level': 'medium', 'opening': 'Алло, у нас пожар!',
        'persona': 'Растерянная женщина', 'fields': make_fields(),
        'field_labels': dict(FIELDS), 'source': 'sample',
        'approved_by': 'Учитель', 'approved_at': '2026-09-29T05:00:00+00:00',
        'created_at': '2026-09-29T05:00:00+00:00',
        'updated_at': '2026-09-29T05:00:00+00:00',
    }
    task.update(overrides)
    return task


class TaskRoundTripTest(unittest.TestCase):

    def test_legacy_caller_task(self):
        doc = base_task()
        rows = docs.task_to_rows(doc, resolve)
        task = row_dict(repo.TASK_COLUMNS, rows['task'])
        self.assertIsNone(rows['task_dds'])
        self.assertIsNone(rows['task_incident'])
        restored = docs.task_from_row(task, name_of=name_of)
        for key in ('id', 'title', 'status', 'workflow', 'level', 'opening',
                    'persona', 'fields', 'field_labels', 'source', 'created_at'):
            self.assertEqual(restored[key], doc[key], key)
        self.assertEqual(restored['approved_by'], 'Учитель')
        self.assertNotIn('format', restored)

    def test_dds_task(self):
        doc = base_task(workflow='dds',
                        incoming_card={'address': 'Ленина 5'},
                        verification_notes='Проверить службы',
                        faults='Обрыв связи',
                        service={'name': '101', 'role': 'Пожарная охрана',
                                 'knowledge': 'Знает адрес'},
                        actions={'action_1': {'expected': 'Вызов', 'criterion': 'Критерий'}},
                        field_labels=None)
        rows = docs.task_to_rows(doc, resolve)
        task = row_dict(repo.TASK_COLUMNS, rows['task'])
        dds = row_dict(repo.TASK_DDS_COLUMNS, rows['task_dds'])
        restored = docs.task_from_row(task, dds, name_of=name_of)
        self.assertEqual(restored['incoming_card'], {'address': 'Ленина 5'})
        self.assertEqual(restored['verification_notes'], 'Проверить службы')
        self.assertEqual(restored['faults'], 'Обрыв связи')
        self.assertEqual(restored['service'], {'name': '101', 'role': 'Пожарная охрана',
                                               'knowledge': 'Знает адрес'})
        self.assertEqual(restored['actions'], {'action_1': {'expected': 'Вызов',
                                                            'criterion': 'Критерий'}})

    def test_incident_v1_task(self):
        doc = base_task(
            format='incident-v1',
            incident_source={'title': 'Пожар', 'report': 'Горит квартира',
                             'fields': {'phone_aon': '123'}, 'class_ids': ['1'],
                             'services': ['101'], 'main_service': '101', 'flags': {}},
            incident_reference={'answer': {'expected_fields': {}}},
            caller_scenario={'turns': [{'role': 'caller', 'text': 'Алло'}]},
            opening='Алло, горим!')
        rows = docs.task_to_rows(doc, resolve)
        task = row_dict(repo.TASK_COLUMNS, rows['task'])
        inc = row_dict(repo.TASK_INCIDENT_COLUMNS, rows['task_incident'])
        restored = docs.task_from_row(task, incident_row=inc, name_of=name_of)
        self.assertEqual(restored['format'], 'incident-v1')
        self.assertEqual(restored['incident_source'],
                         doc['incident_source'])
        self.assertEqual(restored['incident_reference'], doc['incident_reference'])
        self.assertEqual(restored['caller_scenario'], doc['caller_scenario'])
        self.assertEqual(restored['opening'], 'Алло, горим!')
        self.assertEqual(rows['task'][12], 1)  # approved_by_id -> Учитель


class SessionRoundTripTest(unittest.TestCase):

    def _session(self):
        task = base_task()
        return {
            'id': 's-abcdefabcdef', 'student': 'Студент', 'task': task,
            'reference_hash': 'a' * 64, 'status': 'reviewed',
            'effective_level': 'medium',
            'card': {key: '' for key in FIELDS},
            'history': [{'id': 1, 'role': 'caller', 'text': 'Алло, у нас пожар!'},
                        {'id': 2, 'role': 'dispatcher', 'text': 'Какой адрес?'},
                        {'id': 3, 'role': 'caller', 'text': 'Улица Ленина, 5.'}],
            'hints': [{'text': 'Уточните адрес', 'at': '2026-09-29T05:01:00+00:00'}],
            'card_edits': [{'field': 'address', 'before': '', 'after': 'Ленина 5',
                            'at': '2026-09-29T05:01:30+00:00'}],
            'training_reveals': [{'field': 'floors', 'label': 'Этажность', 'value': '5',
                                  'number': 1, 'at': '2026-09-29T05:02:00+00:00'}],
            'machine_assessment': {'percent': 43, 'compared': 7, 'method': 'Сравнение',
                                   'fields': {'address': {'verdict': 'different', 'weight': 3}},
                                   'at': '2026-09-29T05:03:00+00:00'},
            'assessment': {'summary': 'Хорошо', 'percent': 57, 'reference_hash': 'a' * 64,
                           'at': '2026-09-29T05:04:00+00:00',
                           'fields': {'address': {'verdict': 'correct', 'comment': 'ОК',
                                                  'clarification': '',
                                                  'evidence': [{'turn_id': 3, 'quote': 'Улица Ленина, 5.'}],
                                                  'citation_warning': False}}},
            'teacher_decision': {'teacher': 'Учитель', 'grade': 4, 'percent': 67,
                                 'conclusion': 'Зачтено', 'at': '2026-09-29T05:05:00+00:00',
                                 'fields': {'address': {'decision': 'agree', 'comment': 'Верно'}}},
            'training': {'plan_id': 'training-000000000001',
                         'training_id': 'training-000000000001', 'title': 'Пожар',
                         'group': 'Группа 1', 'teacher': 'Учитель', 'seconds': 30,
                         'mode': 'training', 'role': 'operator', 'difficulty': 'medium',
                         'card_index': 1, 'card_total': 3},
            'callback_disclosed': False, 'connection': None, 'call_attempts': 0,
            'next_channel': None, 'timed_out': False, 'forced_finish': None,
            'teacher_note': None, 'teacher_note_by': None, 'teacher_note_at': None,
            'created_at': '2026-09-29T05:00:00+00:00',
            'activated_at': '2026-09-29T05:00:10+00:00',
            'submitted_at': '2026-09-29T05:05:00+00:00',
            'updated_at': '2026-09-29T05:05:00+00:00',
        }

    def _restore(self, doc):
        rows = docs.session_to_rows(doc, resolve)
        session = row_dict(repo.SESSION_COLUMNS, rows['session'])
        turns = [row_dict(repo.SESSION_TURN_COLUMNS, t) for t in rows['turns']]
        hints = [row_dict(repo.SESSION_HINT_COLUMNS, h) for h in rows['hints']]
        edits = [row_dict(repo.SESSION_CARD_EDIT_COLUMNS, e) for e in rows['edits']]
        reveals = [row_dict(repo.SESSION_REVEAL_COLUMNS, r) for r in rows['reveals']]
        machine = None
        if rows['machine'] is not None:
            machine = row_dict(repo.MACHINE_ASSESSMENT_COLUMNS, rows['machine'])
        assessment, assessment_fields = None, []
        if rows['assessment'] is not None:
            assessment = row_dict(repo.AI_ASSESSMENT_COLUMNS, rows['assessment']['row'])
            assessment_fields = [
                row_dict(repo.AI_ASSESSMENT_FIELD_COLUMNS, (1,) + f)
                for f in rows['assessment']['fields']]
        decision, decision_fields = None, []
        if rows['decision'] is not None:
            decision = row_dict(repo.TEACHER_DECISION_COLUMNS, rows['decision']['row'])
            decision_fields = [
                row_dict(repo.TEACHER_DECISION_FIELD_COLUMNS, (1,) + f)
                for f in rows['decision']['fields']]
        return docs.session_from_row(
            session, turns=turns, hints=hints, edits=edits, reveals=reveals,
            machine=machine, assessment=assessment,
            assessment_fields=assessment_fields, decision=decision,
            decision_fields=decision_fields, name_of=name_of)

    def test_full_session_round_trip(self):
        doc = self._session()
        restored = self._restore(doc)
        self.assertEqual(restored['id'], doc['id'])
        self.assertEqual(restored['student'], 'Студент')
        self.assertEqual(restored['status'], 'reviewed')
        self.assertEqual(restored['task'], doc['task'])  # task_snapshot verbatim
        self.assertEqual(restored['reference_hash'], doc['reference_hash'])
        self.assertEqual(restored['card'], doc['card'])
        self.assertEqual(restored['training'], doc['training'])
        self.assertEqual([(t['id'], t['role'], t['text']) for t in restored['history']],
                         [(t['id'], t['role'], t['text']) for t in doc['history']])
        self.assertEqual(restored['hints'], doc['hints'])
        self.assertEqual(restored['card_edits'], doc['card_edits'])
        self.assertEqual(restored['training_reveals'], doc['training_reveals'])
        self.assertEqual(restored['machine_assessment'], doc['machine_assessment'])
        self.assertEqual(restored['assessment']['summary'], doc['assessment']['summary'])
        self.assertEqual(restored['assessment']['percent'], doc['assessment']['percent'])
        self.assertEqual(restored['assessment']['fields']['address']['verdict'], 'correct')
        self.assertEqual(restored['assessment']['fields']['address']['evidence'],
                         doc['assessment']['fields']['address']['evidence'])
        self.assertFalse(restored['assessment']['fields']['address']['citation_warning'])
        self.assertEqual(restored['teacher_decision']['teacher'], 'Учитель')
        self.assertEqual(restored['teacher_decision']['grade'], 4)
        self.assertEqual(restored['teacher_decision']['fields'],
                         doc['teacher_decision']['fields'])
        self.assertEqual(restored['created_at'], doc['created_at'])
        self.assertFalse(restored['timed_out'])

    def test_dds_session_delivered_flags(self):
        doc = self._session()
        doc['status'] = 'active'
        doc['task'] = base_task(workflow='dds', incoming_card={'address': ''},
                                verification_notes='', faults='',
                                service={'name': '101', 'role': 'П', 'knowledge': 'К'},
                                actions={})
        doc['history'] = [
            {'id': 1, 'role': 'system', 'text': 'Назначено задание', 'event': 'assignment'},
            {'id': 2, 'role': 'service', 'text': 'Принято', 'delivered': True},
            {'id': 3, 'role': 'dispatcher', 'text': 'Потеряно', 'delivered': False},
        ]
        doc['card'] = {'address': 'Ленина 5'}
        doc.pop('assessment')
        doc.pop('teacher_decision')
        doc.pop('machine_assessment')
        restored = self._restore(doc)
        self.assertEqual(restored['history'][0]['event'], 'assignment')
        self.assertTrue(restored['history'][1]['delivered'])
        self.assertFalse(restored['history'][2]['delivered'])
        self.assertIsNone(restored['assessment'])
        self.assertIsNone(restored['teacher_decision'])


class CurriculumRoundTripTest(unittest.TestCase):

    def test_scenario(self):
        doc = {'id': 'scenario-1234567890ab', 'title': 'Пожары', 'description': 'Описание',
               'status': 'approved', 'task_ids': ['t-1234567890ab', 't-1234567890ac'],
               'task_difficulties': {'t-1234567890ab': 3, 't-1234567890ac': 5},
               'created_by': 'Учитель', 'approved_by': 'Учитель',
               'approved_at': '2026-09-29T06:00:00+00:00',
               'created_at': '2026-09-29T06:00:00+00:00',
               'updated_at': '2026-09-29T06:00:00+00:00'}
        repo = __import__('storage_repository')
        rows = docs.scenario_to_rows(doc, resolve)
        scenario = row_dict(repo.SCENARIO_COLUMNS, rows['scenario'])
        tasks = [row_dict(repo.SCENARIO_TASK_COLUMNS, (doc['id'],) + t)
                 for t in rows['tasks']]
        restored = docs.scenario_from_row(scenario, tasks, name_of)
        self.assertEqual(restored['id'], doc['id'])
        self.assertEqual(restored['task_ids'], doc['task_ids'])
        self.assertEqual(restored['task_difficulties'], doc['task_difficulties'])
        self.assertEqual(restored['created_by'], 'Учитель')
        self.assertEqual(restored['approved_by'], 'Учитель')

    def test_training(self):
        doc = {'id': 'training-1234567890ab', 'title': 'Тренировка 1',
               'description': '', 'status': 'active', 'mode': 'training', 'seconds': 30,
               'difficulty': 'medium', 'teacher': 'Учитель', 'group': 'Группа 1',
               'scenario_ids': ['scenario-1234567890ab'],
               'participants': [{'student': 'Студент', 'role': 'operator', 'service': ''},
                                {'student': 'Студент2', 'role': 'service', 'service': '101'}],
               'cards': [{'id': 'card-1234567890ab', 'task_id': 't-1234567890ab',
                          'operator_session_id': 's-abcdefabcdef', 'status': 'done',
                          'card': {'address': 'Ленина 5'}, 'services': ['101'],
                          'submitted_at': '2026-09-29T07:00:00+00:00',
                          'dds_by': 'Студент2', 'routed_at': '2026-09-29T07:01:00+00:00',
                          'service_actions': {'101': {'student': 'Студент2',
                                                      'text': 'Выехали', 'at': '2026-09-29T07:02:00+00:00'}}}],
               'created_at': '2026-09-29T07:00:00+00:00',
               'started_at': '2026-09-29T07:00:00+00:00',
               'completed_at': None, 'updated_at': '2026-09-29T07:03:00+00:00'}
        NAMES['Студент2'] = 3
        try:
            repo = __import__('storage_repository')
            rows = docs.training_to_rows(doc, resolve)
            training = row_dict(repo.TRAINING_COLUMNS, rows['training'])
            scenarios = [row_dict(repo.TRAINING_SCENARIO_COLUMNS, (doc['id'], sid))
                         for sid in rows['scenarios']]
            participants = [row_dict(repo.TRAINING_PARTICIPANT_COLUMNS, p)
                            for p in rows['participants']]
            cards = [row_dict(repo.TRAINING_CARD_COLUMNS, c['row']) for c in rows['cards']]
            actions = []
            for card in rows['cards']:
                actions.extend(row_dict(repo.TRAINING_SERVICE_ACTION_COLUMNS, a)
                               for a in card['actions'])
            restored = docs.training_from_row(training, scenarios, participants,
                                              cards, actions, name_of)
            self.assertEqual(restored['id'], doc['id'])
            self.assertEqual(restored['status'], 'active')
            self.assertEqual(restored['scenario_ids'], doc['scenario_ids'])
            self.assertEqual(restored['participants'], doc['participants'])
            self.assertEqual(restored['cards'][0]['id'], 'card-1234567890ab')
            self.assertEqual(restored['cards'][0]['status'], 'done')
            self.assertEqual(restored['cards'][0]['card'], {'address': 'Ленина 5'})
            self.assertEqual(restored['cards'][0]['services'], ['101'])
            self.assertEqual(restored['cards'][0]['service_actions']['101']['text'],
                             'Выехали')
            self.assertEqual(restored['cards'][0]['dds_by'], 'Студент2')
        finally:
            NAMES.pop('Студент2', None)

    def test_material(self):
        doc = {'id': 'material-1234567890ab', 'title': 'Методичка', 'url': 'https://x.ru/doc',
               'description': 'Описание', 'teacher': 'Учитель',
               'created_at': '2026-09-29T08:00:00+00:00'}
        repo = __import__('storage_repository')
        row = row_dict(repo.MATERIAL_COLUMNS, docs.material_to_rows(doc, resolve))
        restored = docs.material_from_row(row, name_of)
        self.assertEqual(restored, doc)


class LoadTsTest(unittest.TestCase):

    def test_postgres_format(self):
        self.assertEqual(load_ts('2026-09-29 05:00:00+00'),
                         '2026-09-29T05:00:00+00:00')
        self.assertEqual(load_ts('2026-09-29 05:00:00.123456+00'),
                         '2026-09-29T05:00:00.123456+00:00')
        self.assertEqual(load_ts('2026-09-29T05:00:00+00:00'),
                         '2026-09-29T05:00:00+00:00')
        self.assertIsNone(load_ts(None))
        # Loaded timestamps are normalized to UTC (like normalize_ts).
        self.assertEqual(load_ts('2026-09-29 05:00:00+07'),
                         '2026-09-28T22:00:00+00:00')


if __name__ == '__main__':
    unittest.main()