"""Unit tests for catalog_importer parsing/mapping (no database required)."""
import json
import tempfile
import unittest
from pathlib import Path

import catalog_importer

CLASSIFIER_FIXTURE = {
    'version': 'fixture-v1',
    'categories': {'1': 'Пожар', '2': 'ДТП'},
    'services': {'101': 'Служба 101', '102': 'Служба 102'},
    'entries': [
        {
            'id': '1000001', 'category': '1', 'group': 'Группа А',
            'statistical_group': 'Стат 1', 'sign1': 'с1', 'sign2': 'с2',
            'sign3': 'с3', 'extra_signs': 'доп', 'title': 'Пожар в квартире',
            'ekp_type': 'Тип 1', 'main_service': '101', 'services': ['101'],
            'rules': [
                {'column': 'N', 'service': '101', 'condition': 'Служба 101', 'value': 'Пожар'},
            ],
        },
        {
            'id': '2000001', 'category': '2', 'group': 'Группа Б',
            'statistical_group': '', 'sign1': '', 'sign2': '', 'sign3': '',
            'extra_signs': '', 'title': 'ДТП', 'ekp_type': '',
            'main_service': '', 'services': ['101', '102'],
            'rules': [
                {'column': 'U', 'service': '102', 'condition': 'Служба 102', 'value': 'ДТП'},
                {'column': 'O', 'service': '101', 'condition': 'Служба 101', 'value': 'ДТП'},
                {'column': 'V', 'service': 'PSC', 'condition': 'ОДС ПСЦ', 'value': 'ДТП'},
            ],
        },
    ],
}

GEO_FIXTURE = {
    'addresses': [
        {'id': 'building-1', 'kind': 'building', 'street': 'Ленина', 'house': '1', 'point': [93.5, 56.2]},
        {'id': 'street-1', 'kind': 'street', 'street': 'Пушкина', 'house': '', 'point': [93.6, 56.3]},
    ],
}


def _write(fixture: dict) -> Path:
    handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(fixture, handle, ensure_ascii=False)
    handle.close()
    return Path(handle.name)


class ClassifierMappingTests(unittest.TestCase):
    def test_counts_and_sorting(self):
        path = _write(CLASSIFIER_FIXTURE)
        try:
            data = catalog_importer.parse_classifier(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([('101', 'Служба 101'), ('102', 'Служба 102')], data['services'])
        self.assertEqual([(1, 'Пожар'), (2, 'ДТП')], data['categories'])
        self.assertEqual(2, len(data['entries']))
        self.assertEqual(4, len(data['entry_services']))

    def test_entry_mapping(self):
        path = _write(CLASSIFIER_FIXTURE)
        try:
            data = catalog_importer.parse_classifier(path)
        finally:
            path.unlink(missing_ok=True)
        first, second = data['entries']
        self.assertEqual('1000001', first['id'])
        self.assertEqual(1, first['category_id'])
        self.assertEqual('Пожар в квартире', first['title'])
        self.assertEqual('101', first['main_service_code'])
        # main_service is empty -> fall back to the first service from the list.
        self.assertEqual('101', second['main_service_code'])
        self.assertEqual('Группа Б', second['group_name'])

    def test_rule_mapping(self):
        path = _write(CLASSIFIER_FIXTURE)
        try:
            data = catalog_importer.parse_classifier(path)
        finally:
            path.unlink(missing_ok=True)
        links = data['entry_services']
        first_link = links[0]
        self.assertEqual('1000001', first_link['entry_id'])
        self.assertEqual('101', first_link['service_code'])
        self.assertEqual('column', first_link['condition_type'])
        self.assertEqual('Служба 101', first_link['condition_text'])
        self.assertEqual('Пожар', first_link['value'])
        self.assertTrue(first_link['is_main'])
        # PSC is conditional (not in entry.services) -> is_main False.
        psc = next(link for link in links if link['service_code'] == 'PSC')
        self.assertFalse(psc['is_main'])


class GeoMappingTests(unittest.TestCase):
    def test_address_and_building_splitting(self):
        path = _write(GEO_FIXTURE)
        try:
            data = catalog_importer.parse_geo_addresses(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(2, len(data['addresses']))
        self.assertEqual(1, len(data['buildings']))
        building = data['addresses'][0]
        self.assertEqual('building-1', building['id'])
        self.assertEqual(56.2, building['lat'])
        self.assertEqual(93.5, building['lon'])
        self.assertEqual([93.5, 56.2], building['point'])
        self.assertEqual('building-1', data['buildings'][0]['id'])
        self.assertNotIn('kind', data['buildings'][0])


if __name__ == '__main__':
    unittest.main()