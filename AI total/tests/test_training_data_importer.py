"""Unit tests for the Этап 3 parsers (no database required).

Covers scanning, task/session/scenario/training/materials parsing, timestamp
normalization, the DDS delivery rule, incident-v1 identity hashing and the
collection of legacy names with role priority.
"""
import json
import tempfile
import unittest
from pathlib import Path

import training_data_importer as importer
import training_data_service as service
from training_data_repository import TASK_COLUMNS

T_LEGACY = 't-abc123000000'
T_DDS = 't-abc123000001'
T_INCIDENT = 't-abc123000002'
S_SESSION = 's-abc123000000'
SCENARIO = 'scenario-abc123000000'
TRAINING = 'training-abc123000000'
CARD = 'card-abc123000000'
MATERIAL = 'material-abc123000000'

FIELDS7 = {
    'address': {'truth': 'Учебный город, ул. Лесная, 12', 'known': 'Я у дома 12',
                'expected': 'Учебный город, ул. Лесная, 12',
                'criterion': 'Адрес уточнён', 'weight': 5},
    'incident': {'truth': 'Горит гараж', 'known': 'Горит гараж',
                 'expected': 'Пожар в гараже', 'criterion': 'Суть сохранена', 'weight': 4},
    'people': {'truth': 'Неизвестно', 'known': 'Не знаю', 'expected': 'Неизвестно',
               'criterion': 'Без домыслов', 'weight': 3},
    'injured': {'truth': 'Неизвестно', 'known': 'Не видел', 'expected': 'Неизвестно',
                'criterion': 'Без домыслов', 'weight': 3},
    'floors': {'truth': '1', 'known': 'Одноэтажный', 'expected': '1',
               'criterion': 'Точность', 'weight': 2},
    'entrance': {'truth': 'Ворота', 'known': 'Ворота', 'expected': 'Ворота',
                 'criterion': 'Точность', 'weight': 2},
    'access': {'truth': 'Неизвестно', 'known': 'Не знаю', 'expected': 'Неизвестно',
               'criterion': 'Без домыслов', 'weight': 2},
}


def legacy_task(identifier=T_LEGACY, **overrides):
    task = {
        'id': identifier, 'title': 'Пожар в гараже', 'status': 'approved',
        'workflow': 'caller', 'level': 'easy',
        'opening': 'Гараж горит, скорее приезжайте!',
        'persona': 'Женщина, очевидец возле гаража.',
        'fields': FIELDS7, 'field_labels': importer.FIELDS,
        'source': 'sample', 'approved_by': 'Преподаватель Иванова',
        'approved_at': '2026-09-01T08:00:00+00:00',
        'created_at': '2026-09-01T07:00:00+00:00',
        'updated_at': '2026-09-01T08:05:00+00:00',
    }
    task.update(overrides)
    return task


class ScanTests(unittest.TestCase):
    def test_scan_reports_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / f'{T_LEGACY}.json').write_text('{}', encoding='utf-8')
            (root / f'{S_SESSION}.json').write_text('{}', encoding='utf-8')
            curriculum = root / 'curriculum'
            curriculum.mkdir()
            (curriculum / f'{SCENARIO}.json').write_text('{}', encoding='utf-8')
            (curriculum / f'{TRAINING}.json').write_text('{}', encoding='utf-8')
            (curriculum / 'materials.json').write_text('[]', encoding='utf-8')
            report = importer.scan(root)
            self.assertTrue(report.data_exists and report.curriculum_exists)
            self.assertEqual([f'{T_LEGACY}.json'], report.task_files)
            self.assertEqual([f'{S_SESSION}.json'], report.session_files)
            self.assertEqual([f'{SCENARIO}.json'], report.scenario_files)
            self.assertEqual([f'{TRAINING}.json'], report.training_files)
            self.assertEqual('materials.json', report.materials_file)
            self.assertTrue(report.available)

    def test_scan_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = importer.scan(Path(tmp))
            self.assertFalse(report.available)


class TaskParserTests(unittest.TestCase):
    def test_parse_legacy_caller(self):
        task = importer.parse_task(legacy_task())
        self.assertIsNotNone(task)
        self.assertEqual(T_LEGACY, task['id'])
        self.assertEqual('legacy', task['format'])
        self.assertEqual('caller', task['workflow'])
        self.assertIsNone(task['identity_hash'])
        self.assertIsNone(task['dds'])
        self.assertIsNone(task['incident'])
        self.assertEqual('Преподаватель Иванова', task['approved_by'])

    def test_parse_dds(self):
        data = legacy_task(identifier=T_DDS, workflow='dds',
                           incoming_card={key: 'x' for key in FIELDS7},
                           verification_notes='Уточнение: дом 14',
                           faults='Адрес указан неверно',
                           service={'name': 'Аварийная служба', 'role': 'дежурный',
                                    'knowledge': 'Ничего не знаю'},
                           actions={key: {'expected': 'e', 'criterion': 'c'}
                                    for key in ('action_validation', 'action_transmission',
                                                'action_confirmation', 'action_recovery')})
        task = importer.parse_task(data)
        self.assertEqual('dds', task['workflow'])
        self.assertEqual('Аварийная служба', task['dds']['service_name'])
        self.assertEqual('дежурный', task['dds']['service_role'])
        self.assertEqual('Адрес указан неверно', task['dds']['faults'])
        self.assertIsNotNone(task['dds']['actions'])

    def test_parse_incident_v1_and_identity_hash(self):
        content = {'title': 'Пожар', 'report': 'Сообщение',
                   'fields': {'caller_name': 'Иван'}, 'class_ids': ['1'],
                   'services': ['101'], 'main_service': '101', 'flags': {}}
        reference = {'answer': {'expected_fields': {'caller_name': {'value': 'Иван'}}}}
        scenario = {'profile': 'neutral'}
        data = legacy_task(identifier=T_INCIDENT, format='incident-v1',
                           incident_source=content, incident_reference=reference,
                           caller_scenario=scenario, opening='Первая реплика',
                           fields={'caller_name': {'truth': 'Иван', 'known': 'Иван',
                                                   'expected': 'Иван',
                                                   'criterion': 'c', 'weight': 1}},
                           field_labels={'caller_name': 'Имя'})
        task = importer.parse_task(data)
        self.assertEqual('incident-v1', task['format'])
        self.assertEqual(importer.compute_identity_hash(data), task['identity_hash'])
        self.assertEqual(64, len(task['identity_hash']))
        # Stable for identical payloads.
        self.assertEqual(task['identity_hash'],
                         importer.compute_identity_hash(legacy_task(
                             identifier=T_INCIDENT, format='incident-v1',
                             incident_source=content, incident_reference=reference,
                             caller_scenario=scenario, opening='Первая реплика',
                             fields={'caller_name': {'truth': 'Иван', 'known': 'Иван',
                                                     'expected': 'Иван',
                                                     'criterion': 'c', 'weight': 1}},
                             field_labels={'caller_name': 'Имя'})))
        self.assertEqual(content, task['incident']['content'])
        self.assertEqual(reference, task['incident']['reference'])

    def test_parse_rejects_broken_records(self):
        self.assertIsNone(importer.parse_task({'id': 'bad'}))
        self.assertIsNone(importer.parse_task(legacy_task(status='deleted')))
        self.assertIsNone(importer.parse_task(legacy_task(id='wrong-id')))


class SessionParserTests(unittest.TestCase):
    def _full_session(self, identifier=S_SESSION, status='reviewed'):
        task = legacy_task()
        return {
            'id': identifier, 'student': 'Студент Ф1',
            'task': task, 'reference_hash': importer.compute_reference_hash(task),
            'status': status, 'created_at': '2026-09-02T09:00:00',
            'activated_at': '2026-09-02T09:00:05+00:00',
            'submitted_at': '2026-09-02T09:20:00+00:00',
            'effective_level': 'easy',
            'card': {'address': 'Учебный город, ул. Лесная, 12'},
            'training': {'plan_id': TRAINING, 'card_index': 1},
            'callback_disclosed': False, 'connection': None,
            'call_attempts': 0, 'next_channel': None, 'timed_out': False,
            'history': [
                {'id': 1, 'role': 'caller', 'text': 'Гараж горит!', 'at': '2026-09-02T09:00:10+00:00'},
                {'id': 2, 'role': 'dispatcher', 'text': 'Какой адрес?', 'source': 'voice', 'at': '2026-09-02T09:00:30+00:00'},
                {'id': 3, 'role': 'caller', 'text': 'Улица Лесная, 12.', 'at': '2026-09-02T09:00:40+00:00'},
                {'id': 4, 'role': 'system', 'text': 'Соединение установлено.', 'event': 'connected', 'at': '2026-09-02T09:01:00+00:00'},
            ],
            'hints': [{'text': 'Уточните адрес.', 'at': '2026-09-02T09:01:10+00:00'}],
            'card_edits': [{'field': 'address', 'before': '', 'after': 'Лесная 12', 'at': '2026-09-02T09:02:00+00:00'}],
            'training_reveals': [{'field': 'address', 'label': 'Адрес', 'value': 'Учебный город, ул. Лесная, 12', 'number': 1, 'at': '2026-09-02T09:03:00+00:00'}],
            'machine_assessment': {'percent': 100, 'compared': 7, 'method': 'test',
                                   'fields': {'address': {'verdict': 'correct', 'weight': 5}},
                                   'at': '2026-09-02T09:20:01+00:00'},
            'assessment': {'summary': 'Хорошо', 'percent': 90, 'reference_hash': 'x' * 64,
                           'at': '2026-09-02T09:21:00+00:00',
                           'fields': {'address': {'verdict': 'correct', 'comment': 'Верно',
                                                  'clarification': '', 'citation_warning': False,
                                                  'evidence': [{'turn_id': 3, 'quote': 'Лесная, 12'}]}}},
            'teacher_decision': {'teacher': 'Преподаватель Иванова', 'grade': 5, 'percent': 100,
                                 'conclusion': 'Отлично', 'at': '2026-09-02T10:00:00+00:00',
                                 'fields': {'address': {'decision': 'agree', 'comment': 'Согласен'}}},
            'teacher_note': 'Молодец', 'teacher_note_by': 'Студент Ф1',
            'teacher_note_at': '2026-09-02T10:01:00+00:00',
            'updated_at': '2026-09-02T10:01:00+00:00',
        }

    def test_parse_full_session(self):
        session = importer.parse_session(self._full_session())
        self.assertIsNotNone(session)
        self.assertEqual(T_LEGACY, session['task_id'])
        self.assertEqual('reviewed', session['status'])
        self.assertEqual(4, len(session['turns']))
        # turn tuple: (turn_no, role, text, source, event, delivered, at)
        self.assertEqual('voice', session['turns'][1][3])
        self.assertEqual('connected', session['turns'][3][4])
        self.assertTrue(session['turns'][0][5])
        self.assertEqual(1, len(session['hints']))
        self.assertEqual(1, len(session['edits']))
        self.assertEqual(1, len(session['reveals']))
        self.assertIsNotNone(session['machine'])
        self.assertIsNotNone(session['assessment'])
        self.assertEqual('false', session['assessment']['fields'][0][4])
        self.assertIsNotNone(session['decision'])
        self.assertEqual('agree', session['decision']['fields'][0][1])
        self.assertTrue(session['teacher_note_by'])

    def test_delivered_flag(self):
        self.assertTrue(importer.delivered_flag({'text': 'x'}))
        self.assertTrue(importer.delivered_flag({'delivered': 'половина', 'delivery': 'partial'}))
        self.assertFalse(importer.delivered_flag({'delivered': '', 'delivery': 'lost'}))
        self.assertFalse(importer.delivered_flag({'delivered': '', 'delivery': 'drop'}))
        self.assertTrue(importer.delivered_flag({'delivered': True}))

    def test_normalize_ts(self):
        self.assertEqual('2026-09-02T09:00:00+00:00',
                         importer.normalize_ts('2026-09-02T09:00:00'))
        self.assertEqual('2026-09-02T09:00:00+00:00',
                         importer.normalize_ts('2026-09-02T09:00:00Z'))
        self.assertIsNone(importer.normalize_ts(None))
        self.assertEqual('2026-09-02T09:00:00+00:00',
                         importer.normalize_ts('2026-09-02T16:00:00+07:00'))

    def test_parse_rejects_broken_sessions(self):
        self.assertIsNone(importer.parse_session({'id': 'bad'}))
        session = self._full_session()
        session['task'] = {'id': 'missing'}
        self.assertIsNone(importer.parse_session(session))
        session = self._full_session(status='weird')
        self.assertIsNone(importer.parse_session(session))


class CurriculumParserTests(unittest.TestCase):
    def test_parse_scenario(self):
        data = {'id': SCENARIO, 'title': 'Сценарий 1',
                'description': 'Описание', 'status': 'approved',
                'task_ids': [T_LEGACY, T_INCIDENT],
                'task_difficulties': {T_LEGACY: 5, T_INCIDENT: 1},
                'created_by': 'Преподаватель Иванова',
                'approved_by': 'Преподаватель Иванова',
                'approved_at': '2026-09-03T08:00:00+00:00',
                'created_at': '2026-09-03T07:00:00+00:00',
                'updated_at': '2026-09-03T08:00:00+00:00'}
        scenario = importer.parse_scenario(data)
        self.assertEqual(2, len(scenario['tasks']))
        self.assertEqual((5, 1), (scenario['tasks'][0][1], scenario['tasks'][1][1]))

    def test_parse_training(self):
        data = {'id': TRAINING, 'title': 'Тренировка 1',
                'description': '', 'status': 'active', 'mode': 'training',
                'seconds': 600, 'difficulty': 'medium',
                'scenario_ids': [SCENARIO],
                'participants': [{'student': 'Студент Ф1', 'role': 'operator', 'service': ''},
                                 {'student': 'Студент Ф2', 'role': 'service', 'service': '101'}],
                'teacher': 'Преподаватель Иванова', 'group': 'Группа 1',
                'started_at': '2026-09-03T09:00:00+00:00',
                'created_at': '2026-09-03T08:00:00+00:00',
                'updated_at': '2026-09-03T09:00:00+00:00',
                'cards': [{'id': CARD,
                           'operator_session_id': S_SESSION,
                           'task_id': T_LEGACY, 'status': 'done',
                           'card': {'address': 'x'}, 'services': ['101'],
                           'submitted_at': '2026-09-03T09:10:00+00:00',
                           'service_actions': {'101': {'student': 'Студент Ф2',
                                                       'text': 'Выехали',
                                                       'at': '2026-09-03T09:11:00+00:00'}}}]}
        training = importer.parse_training(data)
        self.assertEqual('active', training['status'])
        self.assertEqual(2, len(training['participants']))
        self.assertEqual('101', training['participants'][1][2])
        self.assertEqual(1, len(training['cards']))
        self.assertEqual([('101', 'Выехали', '2026-09-03T09:11:00+00:00')],
                         training['cards'][0]['service_actions'])

    def test_parse_materials(self):
        rows = importer.parse_materials([
            {'id': MATERIAL, 'title': 'Методичка', 'url': 'https://x.ru',
             'description': 'Описание', 'teacher': 'Преподаватель Иванова',
             'created_at': '2026-09-03T08:00:00+00:00'},
            'garbage',
        ])
        self.assertEqual(1, len(rows))
        self.assertEqual('Преподаватель Иванова', rows[0]['teacher'])


class NamesAndHelpersTests(unittest.TestCase):
    def test_collect_names_with_role_conflict(self):
        parsed = {
            'tasks': [{'approved_by': 'Имя Конфликт'}],
            'scenarios': [],
            'trainings': [{'teacher': 'Преподаватель Два',
                           'participants': [('Студент Один', 'operator', None)]}],
            'sessions': [{'student': 'Имя Конфликт', 'teacher_note_by': None,
                          'decision': None}],
            'materials': [{'teacher': 'Преподаватель Два'}],
        }
        names = importer.collect_names(parsed)
        self.assertEqual({'student', 'teacher'}, names['Имя Конфликт'])
        self.assertEqual({'student'}, names['Студент Один'])
        self.assertEqual({'teacher'}, names['Преподаватель Два'])

    def test_translit(self):
        self.assertEqual('prepodavatel_ivanova',
                         service.translit('Преподаватель Иванова'))
        self.assertEqual('user', service.translit(''))

    def test_build_rowsets_orders_columns(self):
        warnings = []
        name_map = {'Преподаватель Иванова': 7, 'Студент Ф1': 8}
        parsed = {
            'tasks': [importer.parse_task(legacy_task())],
            'sessions': [], 'scenarios': [], 'trainings': [], 'materials': [],
        }
        sets = service.build_rowsets(parsed, name_map, warnings)
        self.assertEqual(1, len(sets['tasks']))
        row = dict(zip(TASK_COLUMNS, sets['tasks'][0]))
        self.assertEqual(T_LEGACY, row['id'])
        self.assertEqual(7, row['approved_by_id'])
        self.assertEqual([], sets['task_dds'])
        self.assertEqual([], sets['task_incident'])
        self.assertEqual([], warnings)


class LoadJsonTests(unittest.TestCase):
    def test_load_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 't-x.json'
            path.write_text(json.dumps({'a': 1}), encoding='utf-8')
            value, error = importer.load_json(path)
            self.assertEqual({'a': 1}, value)
            self.assertIsNone(error)
            path.write_text('{broken', encoding='utf-8')
            _, error = importer.load_json(path)
            self.assertIsNotNone(error)


if __name__ == '__main__':
    unittest.main()