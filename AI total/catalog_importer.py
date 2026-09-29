"""Parse static catalog sources into repository-ready tuples/dicts.

Reads catalog/classifier.json (services/categories/entries/rules) and
ui/geo/addresses.json, converting them into the shapes consumed by
CatalogRepository.replace_classifier()/replace_geo(). Pure parsing logic —
no database access here, so it is unit-testable without a live server.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent
DEFAULT_CLASSIFIER = ROOT / 'catalog' / 'classifier.json'
DEFAULT_GEO_ADDRESSES = ROOT / 'ui' / 'geo' / 'addresses.json'

# Allowed value columns when an entry cannot decide a main service.
_CONDITION_TYPE_DEFAULT = 'column'


def _load_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def parse_classifier(path=DEFAULT_CLASSIFIER) -> dict:
    """Map classifier.json into four lists for replace_classifier().

    Returns:
        {
          'services': [(code, name), ...],
          'categories': [(category_id, name), ...],
          'entries': [{id, category_id, group_name, statistical_group,
                       sign1..sign3, extra_signs, title, ekp_type,
                       main_service_code}, ...],
          'entry_services': [{entry_id, service_code, condition_type,
                              condition_text, value, is_main}, ...],
        }
    """
    data = _load_json(path)
    services = sorted((str(code), str(name)) for code, name in data.get('services', {}).items())
    categories = sorted((int(cid), str(name)) for cid, name in data.get('categories', {}).items())

    entries: List[dict] = []
    entry_services: List[dict] = []
    for entry in data.get('entries', []):
        services_for_row = entry.get('services') or []
        main_raw = str(entry.get('main_service') or '').strip()
        main_code = main_raw or (str(services_for_row[0]) if services_for_row else None)
        entries.append({
            'id': str(entry['id']),
            'category_id': int(entry['category']),
            'group_name': str(entry.get('group', '')),
            'statistical_group': str(entry.get('statistical_group', '')),
            'sign1': str(entry.get('sign1', '')),
            'sign2': str(entry.get('sign2', '')),
            'sign3': str(entry.get('sign3', '')),
            'extra_signs': str(entry.get('extra_signs', '')),
            'title': str(entry.get('title', '')),
            'ekp_type': str(entry.get('ekp_type', '')),
            'main_service_code': main_code,
        })
        main_set = {str(code) for code in services_for_row}
        for rule in entry.get('rules', []):
            code = str(rule.get('service', ''))
            if not code:
                continue
            entry_services.append({
                'entry_id': str(entry['id']),
                'service_code': code,
                'condition_type': _CONDITION_TYPE_DEFAULT,
                'condition_text': str(rule.get('condition', '')),
                'value': str(rule.get('value', '')),
                'is_main': code in main_set,
            })
    return {'services': services, 'categories': categories,
            'entries': entries, 'entry_services': entry_services}


def parse_geo_addresses(path=DEFAULT_GEO_ADDRESSES) -> dict:
    """Map ui/geo/addresses.json into geo_address/geo_building row lists.

    Each source record has id/kind/street/house/point ([lon, lat]). A row is
    stored as {id, street, house, lat, lon, kind, point} where point keeps the
    original [lon, lat] pair (JSONB) and lat/lon are separate numeric columns.
    """
    data = _load_json(path)
    addresses: List[dict] = []
    buildings: List[dict] = []
    for row in data.get('addresses', []):
        point = row.get('point')
        lon = float(point[0]) if isinstance(point, (list, tuple)) and len(point) > 0 else None
        lat = float(point[1]) if isinstance(point, (list, tuple)) and len(point) > 1 else None
        address = {
            'id': str(row.get('id', '')),
            'street': str(row.get('street', '')),
            'house': str(row.get('house', '')),
            'lat': lat,
            'lon': lon,
            'kind': str(row.get('kind', 'building')),
            'point': list(point) if isinstance(point, (list, tuple)) else None,
        }
        addresses.append(address)
        if address['kind'] == 'building':
            buildings.append({key: address[key] for key in
                              ('id', 'street', 'house', 'lat', 'lon', 'point')})
    return {'addresses': addresses, 'buildings': buildings}


def classify_summary(path=DEFAULT_CLASSIFIER) -> Dict[str, int]:
    """Quick counts for logs/tests without a database."""
    parsed = parse_classifier(path)
    return {key: len(parsed[key]) for key in
            ('services', 'categories', 'entries', 'entry_services')}