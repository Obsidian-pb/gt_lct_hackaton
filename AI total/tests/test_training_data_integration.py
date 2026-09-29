"""Integration tests for the Этап 3 training-data import on a live PostgreSQL.

Writes into a temporary data directory and runs the real import pipeline
(scan -> parse -> user resolution -> full rewrite). Verifies row counts,
idempotency, user deduplication with role priority, the legacy name map and
referential integrity. The suite is skipped when the database is unreachable.

NOTE: import_all() rewrites the educational tables of the shared database by
design (the source of truth on this stage is still JSON files). After the run
the throwaway rows are removed and the created users are deleted.
"""
import json
import tempfile
import unittest
import uuid
from pathlib import Path

try:
    import db_config
    import db_connection
    db_connection.connect_from_config(db_config.get_db_config()).close()
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

if DB_AVAILABLE:
    import training_data_importer as importer
    import training_data_repository
    import training_data_service
    from training_data_importer import FIELDS


def _write(root: Path, rel: str, value) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def _fixture_task(identifier, **extra):
    fields = {key: {'truth': f'{key}-truth', 'known': f'{key}-known',
                    'expected': f'{key}-expected', 'criterion': 'c', 'weight': 3}
              for key in FIELDS}
    return {
        'id': identifier, 'title': 'Фикстура: пожар в гараже', 'status': 'approved',
        'workflow': 'caller', 'level': 'easy',
        'opening': 'Гараж горит!', 'persona': 'Очевидец', 'fields': fields,
        'field_labels': FIELDS, 'source': 'sample', **extra}


@unittest.skipUnless(DB_AVAILABLE, 'PostgreSQL недоступен — интеграционные тесты учебных данных пропущены.')
class TrainingDataLiveTests(unittest.TestCase):
    T_LEGACY = 't-abc100000000'
    T_INCIDENT = 't-abc100000001'
    T_ORPHAN = 't-abc100000099'
    S_SESSION = 's-abc100000000'
    S_ORPHAN = 's-abc100000001'
    SCENARIO = 'scenario-abc100000000'
    TRAINING = 'training-abc100000000'
    CARD = 'card-abc100000000'
    MATERIAL = 'material-abc100000000'

    @classmethod
    def setUpClass(cls):
        cls.repo = training_data_repository.TrainingDataRepository()
        cls.repo.ensure_schema()
        cls.suffix = uuid.uuid4().hex[:8]
        cls.teacher = f'Преподаватель Импорт {cls.suffix}'
        cls.student = f'Студент Импорт {cls.suffix}'

    @classmethod
    def tearDownClass(cls):
        # Remove the imported fixtures and the users they created.
        with cls.repo._connect() as connection:
            with connection.transaction():
                cls.repo.truncate_all(connection)
                rows = connection.execute(
                    'SELECT id FROM "user" WHERE display_name LIKE '
                    + db_connection.quote_literal(f'%{cls.suffix}%'))
                for row in rows:
                    connection.execute(
                        'DELETE FROM "user" WHERE id = '
                        + db_connection.quote_literal(int(row[0])))

    def _build_fixture_dir(self) -> str:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        self.addCleanup(tmp.cleanup)
        approved_at = '2026-09-20T08:00:00+00:00'
        created_at = '2026-09-20T07:00:00+00:00'

        task_legacy = _fixture_task(self.T_LEGACY, approved_by=self.teacher,
                                    approved_at=approved_at, created_at=created_at,
                                    updated_at=approved_at)
        content = {'title': 'Пожар на балконе', 'report': 'Сообщение заявителя',
                   'fields': {'caller_name': 'Иван'}, 'class_ids': ['1'],
                   'services': ['101'], 'main_service': '101', 'flags': {}}
        reference = {'answer': {'expected_fields': {'caller_name': {'value': 'Иван'}}}}
        task_incident = _fixture_task(
            self.T_INCIDENT, format='incident-v1',
            incident_source=content, incident_reference=reference,
            caller_scenario={'profile': 'neutral'}, opening='Первая реплика',
            fields={'caller_name': {'truth': 'Иван', 'known': 'Иван',
                                    'expected': 'Иван', 'criterion': 'c', 'weight': 1}},
            field_labels={'caller_name': 'Имя заявителя'},
            approved_by=self.teacher, approved_at=approved_at,
            created_at=created_at, updated_at=approved_at)

        session = {
            'id': self.S_SESSION, 'student': self.student, 'task': task_legacy,
            'reference_hash': 'a' * 64, 'status': 'reviewed',
            'created_at': '2026-09-21T09:00:00', 'activated_at': '2026-09-21T09:00:05+00:00',
            'submitted_at': '2026-09-21T09:20:00+00:00', 'effective_level': 'easy',
            'card': {'address': 'Учебный город, ул. Лесная, 12'},
            'callback_disclosed': False, 'call_attempts': 0, 'timed_out': False,
            'history': [
                {'id': 1, 'role': 'caller', 'text': 'Гараж горит!', 'at': '2026-09-21T09:00:10+00:00'},
                {'id': 2, 'role': 'dispatcher', 'text': 'Адрес?', 'source': 'voice', 'at': '2026-09-21T09:00:30+00:00'},
            ],
            'hints': [{'text': 'Уточните адрес.', 'at': '2026-09-21T09:01:00+00:00'}],
            'card_edits': [{'field': 'address', 'before': '', 'after': 'Лесная 12',
                            'at': '2026-09-21T09:02:00+00:00'}],
            'training_reveals': [{'field': 'address', 'label': 'Адрес', 'value': 'Лесная 12',
                                  'number': 1, 'at': '2026-09-21T09:03:00+00:00'}],
            'machine_assessment': {'percent': 100, 'compared': 7, 'method': 'test',
                                   'fields': {}, 'at': '2026-09-21T09:20:01+00:00'},
            'assessment': {'summary': 'Хорошо', 'percent': 90, 'reference_hash': 'b' * 64,
                           'at': '2026-09-21T09:21:00+00:00',
                           'fields': {'address': {'verdict': 'correct', 'comment': 'Верно',
                                                  'clarification': '', 'citation_warning': False,
                                                  'evidence': []}}},
            'teacher_decision': {'teacher': self.teacher, 'grade': 5, 'percent': 100,
                                 'conclusion': 'Отлично', 'at': '2026-09-21T10:00:00+00:00',
                                 'fields': {'address': {'decision': 'agree', 'comment': 'Ок'}}},
            'teacher_note': 'Молодец', 'teacher_note_by': self.student,
            'teacher_note_at': '2026-09-21T10:01:00+00:00',
            'updated_at': '2026-09-21T10:01:00+00:00',
        }
        orphan_session = {
            'id': self.S_ORPHAN, 'student': self.student,
            'task': _fixture_task(self.T_ORPHAN), 'reference_hash': 'c' * 64,
            'status': 'submitted', 'created_at': '2026-09-21T11:00:00+00:00',
            'card': {}, 'history': [],
        }

        scenario = {
            'id': self.SCENARIO, 'title': 'Сценарий импорта',
            'description': '', 'status': 'approved',
            'task_ids': [self.T_LEGACY, self.T_INCIDENT],
            'task_difficulties': {self.T_LEGACY: 5, self.T_INCIDENT: 2},
            'created_by': self.teacher, 'approved_by': self.teacher,
            'approved_at': approved_at, 'created_at': created_at, 'updated_at': approved_at,
        }
        training = {
            'id': self.TRAINING, 'title': 'Тренировка импорта',
            'description': '', 'status': 'active', 'mode': 'training', 'seconds': 600,
            'difficulty': 'medium', 'scenario_ids': [self.SCENARIO],
            'participants': [{'student': self.student, 'role': 'operator', 'service': ''},
                             {'student': f'{self.student} 2', 'role': 'service', 'service': '101'}],
            'teacher': self.teacher, 'group': 'Группа импорта',
            'created_at': created_at, 'started_at': '2026-09-21T09:00:00+00:00',
            'updated_at': '2026-09-21T09:10:00+00:00',
            'cards': [{'id': self.CARD, 'operator_session_id': self.S_SESSION,
                       'task_id': self.T_LEGACY, 'status': 'done',
                       'card': {'address': 'Лесная 12'}, 'services': ['101'],
                       'submitted_at': '2026-09-21T09:10:00+00:00',
                       'service_actions': {'101': {'student': f'{self.student} 2',
                                                   'text': 'Выехали',
                                                   'at': '2026-09-21T09:11:00+00:00'}}}],
        }
        materials = [{'id': self.MATERIAL, 'title': 'Методичка',
                      'url': 'https://example.org/doc', 'description': '',
                      'teacher': self.teacher, 'created_at': created_at}]

        _write(root, f'{self.T_LEGACY}.json', task_legacy)
        _write(root, f'{self.T_INCIDENT}.json', task_incident)
        _write(root, f'{self.S_SESSION}.json', session)
        _write(root, f'{self.S_ORPHAN}.json', orphan_session)
        _write(root, f'curriculum/{self.SCENARIO}.json', scenario)
        _write(root, f'curriculum/{self.TRAINING}.json', training)
        _write(root, 'curriculum/materials.json', materials)
        return tmp.name

    def test_import_counts_and_idempotency(self):
        directory = self._build_fixture_dir()
        result = training_data_service.import_all(directory)
        counts = result['counts']
        self.assertEqual(2, counts['task'])
        self.assertEqual(1, counts['task_incident_source'])
        self.assertEqual(1, counts['scenario'])
        self.assertEqual(1, counts['training'])
        self.assertEqual(1, counts['material'])
        self.assertEqual(1, counts['session'])          # orphan session skipped
        self.assertEqual(2, counts['session_turn'])
        self.assertEqual(1, counts['machine_assessment'])
        self.assertEqual(1, counts['ai_assessment'])
        self.assertEqual(1, counts['teacher_decision'])
        self.assertEqual(1, counts['training_card'])
        self.assertEqual(1, counts['training_service_action'])
        self.assertGreater(counts['legacy_name_map'], 0)
        self.assertEqual([], result['integrity_issues'])
        self.assertTrue(any(self.S_ORPHAN in w for w in result['warnings']),
                        msg='ожидали предупреждение о сиротской сессии')

        # Idempotency: a second import rewrites to the same counts.
        before = self._count_users_by_suffix()
        result_again = training_data_service.import_all(directory)
        self.assertEqual(counts, result_again['counts'])
        after = self._count_users_by_suffix()
        self.assertEqual(before, after, 'повторный импорт не должен плодить пользователей')

    def _count_users_by_suffix(self) -> int:
        with self.repo._connect() as connection:
            row = connection.fetchone(
                'SELECT count(*) FROM "user" WHERE display_name LIKE '
                + db_connection.quote_literal(f'%{self.suffix}%'))
        return int(row[0]) if row else 0

    def test_role_priority_and_legacy_map(self):
        directory = self._build_fixture_dir()
        training_data_service.import_all(directory)
        # self.student is used as a student and as teacher_note_by -> one user
        # promoted to teacher; legacy_name_map has a single row per name whose
        # kind reflects the highest role.
        with self.repo._connect() as connection:
            rows = connection.execute(
                'SELECT lm.name, u.role, lm.kind FROM legacy_name_map lm'
                ' JOIN "user" u ON u.id = lm.user_id WHERE lm.name = '
                + db_connection.quote_literal(self.student))
        self.assertEqual(1, len(rows))
        self.assertEqual('teacher', rows[0][1])
        self.assertEqual('teacher', rows[0][2])

    def test_incident_identity_hash_unique(self):
        directory = self._build_fixture_dir()
        result = training_data_service.import_all(directory)
        self.assertEqual([], result['integrity_issues'])
        with self.repo._connect() as connection:
            rows = connection.execute(
                'SELECT id, identity_hash FROM task'
                ' WHERE format = ' + db_connection.quote_literal('incident-v1'))
        self.assertEqual(1, len(rows))
        task_id, identity_hash = rows[0]
        self.assertEqual(self.T_INCIDENT, task_id)
        self.assertEqual(64, len(identity_hash))
        # identity_hash is NULL for legacy tasks.
        with self.repo._connect() as connection:
            row = connection.fetchone(
                'SELECT identity_hash FROM task WHERE id = '
                + db_connection.quote_literal(self.T_LEGACY))
        self.assertIsNone(row[0])

    def test_parser_scan_check_state(self):
        directory = self._build_fixture_dir()
        training_data_service.import_all(directory)
        state = training_data_service.check_state(directory)
        self.assertTrue(state['report'].available)
        self.assertEqual('2.3.0', state['version'])
        self.assertEqual([], state['issues'])
        self.assertEqual(2, state['counts']['task'])

    def test_schema_version(self):
        self.assertEqual('2.3.0', self.repo.migration_version())


if __name__ == '__main__':
    unittest.main()