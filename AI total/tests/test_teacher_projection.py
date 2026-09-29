import unittest
from unittest.mock import patch

import teacher_portal
from storage_repository import StorageRepository


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql):
        self.sql = sql
        return self.rows


class _Storage:
    def __init__(self, repository):
        self._repo = repository


class _Engine:
    def __init__(self, repository):
        self.storage = _Storage(repository)
        self.calls = []

    def list_items(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        if kind == 's':
            raise AssertionError('DB overview must not load full session documents')
        return []


class TeacherProjectionTests(unittest.TestCase):
    def test_overview_uses_projection_and_preserves_session_shape_and_category(self):
        class Repository:
            def __init__(self):
                self.teacher = None

            def list_sessions_summary(self, teacher=None):
                self.teacher = teacher
                return [{
                    'id': 's-0123456789ab', 'student': 'Ученик', 'title': 'Задача',
                    'task_id': 't-0123456789ab', 'status': 'reviewed', 'level': 'medium',
                    'workflow': 'caller', 'created_at': '2026-09-29T10:00:00+00:00',
                    'updated_at': '2026-09-29T11:00:00+00:00', 'duration_seconds': 60,
                    'filled': 2, 'total_fields': 7, 'grade': 5, 'machine_percent': 80,
                    'ai_percent': 75, 'final_percent': 90, 'ai_remarks': 1,
                    'training': {'plan_id': 'plan-123456'}, 'comment': 'Заметка',
                    'category_class_ids': ['1'],
                }]

        repository = Repository()
        engine = _Engine(repository)
        result = teacher_portal.dispatch(
            engine, 'teacher_dashboard', {'_auth_user': {'id': 17, 'role': 'teacher'}})

        self.assertEqual(repository.teacher, 17)
        self.assertEqual(len(result['sessions']), 1)
        row = result['sessions'][0]
        self.assertEqual(row['category'], teacher_portal.CLASS_CATEGORIES.get('1', ''))
        for field, expected in {
            'id': 's-0123456789ab', 'student': 'Ученик', 'title': 'Задача',
            'task_id': 't-0123456789ab', 'status': 'reviewed', 'filled': 2,
            'total_fields': 7, 'grade': 5, 'machine_percent': 80, 'ai_percent': 75,
            'final_percent': 90, 'ai_remarks': 1, 'comment': 'Заметка',
        }.items():
            self.assertEqual(row[field], expected, field)
        self.assertNotIn('category_class_ids', row)
        self.assertEqual(engine.calls, [('t', {'teacher': 17})])

    def test_resolve_student_rejects_duplicate_display_names(self):
        repository = StorageRepository(config={})
        connection = _Connection([(11,), (12,)])
        with patch.object(repository, '_connect', return_value=connection):
            with self.assertRaisesRegex(ValueError, 'уникальный логин'):
                repository.resolve_student('Одно имя')
        self.assertIn('role =', connection.sql)
        self.assertIn('is_active = TRUE', connection.sql)
        connection.rows = [(11,)]
        with patch.object(repository, '_connect', return_value=connection):
            self.assertEqual(repository.resolve_student('student11'), 11)

    def test_summary_projects_scalars_and_applies_teacher_filter_in_sql(self):
        row = (
            's-0123456789ab', 'Ученик', 'Задача', 't-0123456789ab', 'reviewed',
            'medium', 'caller', '2026-09-29 10:00:00+00', '2026-09-29 11:00:00+00',
            '60', '2', '7', '5', '80', '75', '90', '1',
            '{"plan_id":"plan-123456"}', 'Заметка', '["1"]',
        )
        connection = _Connection([row])
        repository = StorageRepository(config={})
        with patch.object(repository, '_connect', return_value=connection):
            result = repository.list_sessions_summary(teacher=17)

        sql = connection.sql
        self.assertIn('s.task_id IN (SELECT id FROM task WHERE approved_by_id = 17)', sql)
        self.assertIn('sg.teacher_id = 17', sql)
        self.assertIn('tr.teacher_id = 17', sql)
        self.assertNotIn('s.task_snapshot,', sql)
        self.assertNotIn('s.card,', sql)
        self.assertEqual(result[0]['student'], 'Ученик')
        self.assertEqual(result[0]['duration_seconds'], 60)
        self.assertEqual(result[0]['filled'], 2)
        self.assertEqual(result[0]['total_fields'], 7)
        self.assertEqual(result[0]['ai_remarks'], 1)
        self.assertEqual(result[0]['training'], {'plan_id': 'plan-123456'})
        self.assertEqual(result[0]['category_class_ids'], ['1'])


if __name__ == '__main__':
    unittest.main()
