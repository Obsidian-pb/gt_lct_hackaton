import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from ai_core import Engine
from storage_adapter import StorageAdapter


class StorageAdapterOwnerListTest(unittest.TestCase):
    def test_owner_filter_does_not_fall_back_to_unfiltered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'curriculum'
            root.mkdir()
            (root / 'scenario-private.json').write_text(
                json.dumps({'id': 'scenario-private', 'created_by': 'other'}),
                encoding='utf-8')
            adapter = StorageAdapter.__new__(StorageAdapter)
            adapter.directory = Path(directory)
            adapter.mode = 'files-to-db'
            adapter._repo = Mock()
            adapter._repo.list_scenarios.return_value = []

            result = adapter.resource_list('scenario', owner=17)

            self.assertEqual(result, [])
            adapter._repo.list_scenarios.assert_called_once_with(owner=17)

    def test_owner_filter_without_database_does_not_expose_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'curriculum'
            root.mkdir()
            (root / 'training-private.json').write_text(
                json.dumps({'id': 'training-private', 'teacher': 'other'}),
                encoding='utf-8')
            adapter = StorageAdapter.__new__(StorageAdapter)
            adapter.directory = Path(directory)
            adapter.mode = 'files'
            adapter._repo = None

            self.assertEqual(adapter.resource_list('training', owner=17), [])

    def test_file_only_engine_filters_owned_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'curriculum'
            root.mkdir()
            for identifier, owner_id in [('scenario-owned', 17), ('scenario-foreign', 18)]:
                (root / (identifier + '.json')).write_text(json.dumps({
                    'id': identifier, 'created_at': '2026-01-01', 'owner_id': owner_id}), encoding='utf-8')
            engine = Engine(Mock(), directory)
            self.assertEqual([item['id'] for item in engine.resource_list('scenario', owner=17)], ['scenario-owned'])

    def test_material_owner_filter_does_not_fall_back_to_unfiltered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'curriculum'
            root.mkdir()
            (root / 'materials.json').write_text(
                json.dumps([{'id': 'material-private', 'teacher': 'other'}]),
                encoding='utf-8')
            adapter = StorageAdapter.__new__(StorageAdapter)
            adapter.directory = Path(directory)
            adapter.mode = 'files-to-db'
            adapter._repo = Mock()
            adapter._repo.list_materials.return_value = []

            result = adapter.materials_items(owner=17)

            self.assertEqual(result, [])
            adapter._repo.list_materials.assert_called_once_with(owner=17)

    def test_file_only_engine_does_not_expose_unfiltered_owner_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'curriculum'
            root.mkdir()
            (root / 'scenario-private.json').write_text(
                json.dumps({'id': 'scenario-private', 'created_at': '2026-01-01'}),
                encoding='utf-8')
            (root / 'materials.json').write_text(
                json.dumps([{'id': 'material-private', 'teacher': 'other'}]),
                encoding='utf-8')
            engine = Engine(Mock(), directory)

            self.assertEqual(engine.resource_list('scenario', owner=17), [])
            self.assertEqual(engine.materials_items(owner=17), [])


if __name__ == '__main__':
    unittest.main()
