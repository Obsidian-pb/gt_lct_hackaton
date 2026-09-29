"""Integration tests for the storage layer (Этап 5) against a live PostgreSQL.

Skipped automatically when the database is unreachable. Every test uses unique
identifiers and cleans up its own rows.
"""
from __future__ import annotations

import unittest
import uuid

import db_config
import db_connection
from storage_repository import StorageRepository


def _suffix():
    return uuid.uuid4().hex[:12]


def _task_doc(task_id, title='Тестовая задача'):
    return {'id': task_id, 'title': title, 'status': 'approved',
            'workflow': 'caller', 'level': 'medium', 'opening': 'Алло!',
            'persona': 'Тест', 'fields': {}, 'source': 'integration-test',
            'created_at': None, 'updated_at': None}


def _session_doc(session_id, task_doc, student):
    return {'id': session_id, 'student': student, 'status': 'active',
            'task': task_doc, 'reference_hash': 'f' * 64,
            'card': {'address': ''},
            'history': [{'id': 1, 'role': 'caller', 'text': 'Алло!'}],
            'hints': [], 'card_edits': [], 'training_reveals': [],
            'training': None, 'created_at': None, 'updated_at': None}


class StorageIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        config = db_config.get_db_config()
        try:
            with db_connection.connect_from_config(config):
                pass
        except Exception as exc:  # noqa: BLE001 - skip when DB is absent
            raise unittest.SkipTest(f'PostgreSQL недоступен: {exc}')
        cls.repo = StorageRepository(config)
        cls.repo.ensure_schema()

    # ----------------------------------------------------------- task/session

    def test_task_and_session_live_round_trip(self):
        suffix = _suffix()
        task_id, session_id = 't-' + suffix, 's-' + suffix
        task = _task_doc(task_id)
        session = _session_doc(session_id, task, 'Ит-студент-' + suffix)
        self.repo.upsert_task(task)
        self.repo.upsert_session(session)
        self.repo.upsert_task(task)   # idempotent upsert
        loaded_task = self.repo.load_task(task_id)
        self.assertEqual(loaded_task['id'], task_id)
        loaded = self.repo.load_session(session_id)
        self.assertEqual(loaded['id'], session_id)
        self.assertEqual(loaded['student'], 'Ит-студент-' + suffix)
        self.assertEqual(loaded['history'][0]['text'], 'Алло!')
        self.assertTrue(any(row['id'] == task_id for row in self.repo.list_tasks()))
        self.assertTrue(any(row['id'] == session_id for row in self.repo.list_sessions()))
        self.assertTrue(self.repo.exists_task(task_id))
        self._cleanup_session(session_id, task_id)

    def test_curriculum_resources_live(self):
        suffix = _suffix()
        task_id, scenario_id, training_id = ('t-' + suffix, 'scenario-' + suffix,
                                             'training-' + suffix)
        task = _task_doc(task_id)
        self.repo.upsert_task(task)
        scenario = {'id': scenario_id, 'title': 'Сценарий', 'description': '',
                    'status': 'approved', 'created_by': None, 'approved_by': None,
                    'approved_at': None, 'created_at': None, 'updated_at': None}
        self.repo.upsert_scenario(scenario)
        training = {
            'id': training_id, 'title': 'Тренировка', 'description': '',
            'status': 'prepared', 'mode': 'training', 'seconds': 30,
            'difficulty': 'medium', 'teacher': None, 'group': None,
            'scenario_ids': [scenario_id], 'participants': [], 'cards': [],
            'created_at': None, 'started_at': None, 'completed_at': None,
            'updated_at': None}
        self.repo.upsert_training(training)
        material = {'id': 'material-' + suffix, 'title': 'Материал',
                    'url': 'https://example.com/doc', 'description': '',
                    'teacher': None, 'created_at': None}
        self.repo.upsert_material(material)
        self.assertEqual(self.repo.load_scenario(scenario_id)['id'], scenario_id)
        self.assertEqual(self.repo.load_training(training_id)['scenario_ids'],
                         [scenario_id])
        self.assertTrue(any(m['id'] == material['id']
                            for m in self.repo.list_materials()))
        self.repo.delete_training(training_id)
        self.repo.delete_scenario(scenario_id)
        self._cleanup_session(None, task_id)

    # ---------------------------------------------------------------- workshop

    def _card(self, suffix):
        return {'id': 'test-card-' + suffix, 'number': 'К-IT' + suffix[:4].upper(),
                'status': 'draft', 'revision': 1,
                'title': 'Пожар', 'report': 'Горит квартира',
                'fields': {'phone_aon': '123'}, 'class_ids': ['1'],
                'services': ['101'], 'main_service': '101', 'flags': {},
                'provenance': {'source': 'manual'},
                'history': [{'at': None, 'action': 'created',
                             'text': 'Создано вручную'}],
                'reference': {'answer': {'expected_fields': {}}}}

    def test_workshop_live_crud(self):
        suffix = _suffix()
        card = self._card(suffix)
        number = card['number']
        created = self.repo.workshop_create(card, None)
        self.assertEqual(created['number'], number)
        listed = self.repo.workshop_list()
        self.assertTrue(any(item['number'] == number for item in listed))
        full = self.repo.workshop_get(number)
        self.assertEqual(full['title'], 'Пожар')
        self.assertEqual(full['status'], 'draft')
        self.assertEqual(len(full['history']), 1)
        # update content
        full['title'] = 'Пожар в подвале'
        full['revision'] = 2
        updated = self.repo.workshop_update(number, full, None)
        self.assertEqual(updated['title'], 'Пожар в подвале')
        # approve -> version snapshot + status
        approved = self.repo.workshop_approve(number, {'teacher': 'Учитель ИТ',
                                                       'note': 'ОК', 'at': None}, None)
        self.assertEqual(approved['status'], 'approved')
        # reopen
        reopened = self.repo.workshop_reopen(number, None)
        self.assertEqual(reopened['status'], 'draft')
        self.assertTrue(self.repo.workshop_delete(number))

    def test_workshop_import_upsert_by_number(self):
        suffix = _suffix()
        card = self._card(suffix)
        imported = self.repo.workshop_import([card], None)
        self.assertEqual(imported, 1)
        card['title'] = 'Изменён после импорта'
        again = self.repo.workshop_import([card], None)  # upsert by number
        self.assertEqual(again, 1)
        self.assertEqual(self.repo.workshop_get(card['number'])['title'],
                         'Изменён после импорта')
        self.assertTrue(self.repo.workshop_delete(card['number']))

    # ---------------------------------------------------------------- cleanup

    def _cleanup_session(self, session_id, task_id):
        repo = self.repo
        with repo._connect() as connection:
            if session_id:
                connection.execute('DELETE FROM "session" WHERE id = '
                                   + db_connection.quote_literal(session_id))
            if task_id:
                connection.execute('DELETE FROM task WHERE id = '
                                   + db_connection.quote_literal(task_id))


if __name__ == '__main__':
    unittest.main()