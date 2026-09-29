import unittest
from contextlib import nullcontext
from unittest.mock import Mock

import insights_service
from storage_repository import SCHEMA_STATEMENTS, StorageRepository


class InsightsServiceTests(unittest.TestCase):
    def test_insight_cache_migration_and_upsert_share_normalized_key(self):
        dedupe_sql = next(statement for statement in SCHEMA_STATEMENTS
                          if statement.startswith('DELETE FROM insight_report'))
        index_sql = next(statement for statement in SCHEMA_STATEMENTS
                         if statement.startswith('CREATE UNIQUE INDEX idx_insight_report_group_period'))
        self.assertIn("COALESCE(older.owner_id, 0)", dedupe_sql)
        self.assertIn("COALESCE(older.group_name, '')", dedupe_sql)
        self.assertIn("COALESCE(owner_id, 0)", index_sql)
        self.assertIn("COALESCE(group_name, '')", index_sql)

        repository = StorageRepository.__new__(StorageRepository)
        connection = Mock()
        repository._connect = Mock(return_value=nullcontext(connection))
        repository.save_insight_report(None, '2026-09-29', {}, None)
        upsert_sql = connection.execute.call_args.args[0]
        self.assertIn("COALESCE(owner_id, 0)", upsert_sql)
        self.assertIn("COALESCE(group_name, '')", upsert_sql)

    def test_postgres_timestamp_cache_matches_source_timestamp(self):
        repository = StorageRepository.__new__(StorageRepository)
        connection = Mock()
        connection.execute.return_value = [
            ('{"summary":"Кэш"}', '2026-09-29 10:00:00+00')]
        repository._connect = Mock(return_value=nullcontext(connection))

        cached = repository.get_insight_report(None, '2026-09-29')

        self.assertEqual(cached['source_updated_at'], '2026-09-29T10:00:00+00:00')

    def setUp(self):
        self.provider = Mock()
        self.provider.generate.return_value = {
            'summary': 'Ошибки в адресе',
            'recommendations': 'Повторить уточнение адреса'}
        self.engine = Mock(provider=self.provider)

    def test_returns_matching_cached_report_without_ai_call(self):
        repository = Mock()
        report = {'works': 2, 'counts': {'адрес': 1},
                  'summary': 'Кэш', 'recommendations': 'Кэш-рекомендация'}
        repository.insight_source.return_value = ('2026-09-29T10:00:00+00:00', 2,
                                                   {'адрес': 1})
        repository.get_insight_report.return_value = {
            'source_updated_at': '2026-09-29T10:00:00+00:00', 'report': report}
        self.engine.storage = Mock(_repo=repository)

        result = insights_service.get_insights(self.engine, 'Группа А', owner=71)

        self.assertEqual(result, report)
        repository.insight_source.assert_called_once_with('Группа А', owner=71)
        repository.get_insight_report.assert_called_once_with(
            'Группа А', unittest.mock.ANY, owner=71)
        self.provider.generate.assert_not_called()
        repository.save_insight_report.assert_not_called()

    def test_stale_cache_is_regenerated_and_saved(self):
        repository = Mock()
        repository.insight_source.return_value = ('2026-09-29T11:00:00+00:00', 3,
                                                   {'адрес': 2})
        repository.get_insight_report.return_value = {
            'source_updated_at': '2026-09-29T10:00:00+00:00', 'report': {}}
        self.engine.storage = Mock(_repo=repository)

        result = insights_service.get_insights(self.engine, 'Группа А')

        self.assertEqual(result['works'], 3)
        self.assertEqual(result['counts'], {'адрес': 2})
        self.provider.generate.assert_called_once()
        repository.save_insight_report.assert_called_once_with(
            'Группа А', unittest.mock.ANY, result, '2026-09-29T11:00:00+00:00',
            owner=None)

    def test_force_refresh_ignores_matching_cache(self):
        repository = Mock()
        repository.insight_source.return_value = ('2026-09-29T11:00:00+00:00', 1, {})
        repository.get_insight_report.return_value = {
            'source_updated_at': '2026-09-29T11:00:00+00:00', 'report': {}}
        self.engine.storage = Mock(_repo=repository)

        insights_service.get_insights(self.engine, force=True)

        self.provider.generate.assert_called_once()
        repository.save_insight_report.assert_called_once()

    def test_document_fallback_generates_report_without_cache(self):
        session = {
            'assessment': {'fields': {'address': {'verdict': 'incorrect'}}},
            'task': {'field_labels': {'address': 'Адрес'}}, 'training': None}
        self.engine.storage = None
        self.engine.list_items.return_value = [session]

        result = insights_service.get_insights(self.engine)

        self.assertEqual(result['works'], 1)
        self.assertEqual(result['counts'], {'Адрес': 1})
        self.provider.generate.assert_called_once()

    def test_teacher_report_requires_database_owner_filter(self):
        self.engine.storage = None
        self.engine.list_items.return_value = [{'assessment': {'fields': {}},
                                                'training': {'group': 'Группа А'}}]

        with self.assertRaisesRegex(ValueError, 'требуется база данных'):
            insights_service.get_insights(self.engine, 'Группа А', owner=71)

        self.engine.list_items.assert_not_called()
        self.provider.generate.assert_not_called()

    def test_no_assessed_work_raises(self):
        self.engine.storage = None
        self.engine.list_items.return_value = []

        with self.assertRaisesRegex(ValueError, 'сначала проверьте'):
            insights_service.get_insights(self.engine)

        self.provider.generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
