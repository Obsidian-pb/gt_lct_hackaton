"""Catalog business logic: REST-facing CRUD over reference tables.

Raises CatalogError(status, code, message); the HTTP router maps it to
APIError. Zero third-party dependencies — all persistence goes through
catalog_repository.CatalogRepository and db_connection.quote_literal().
"""
from __future__ import annotations

from typing import List, Optional

import catalog_repository
from db_connection import DbConnectionError


class CatalogError(Exception):
    """Catalog operation failure with an HTTP-like status."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def _repo() -> catalog_repository.CatalogRepository:
    return catalog_repository.CatalogRepository()


def _required(value, name: str, length: int = 255) -> str:
    text = str(value or '').strip()
    if not text:
        raise CatalogError(422, 'invalid_field', f'Укажите {name}.')
    if len(text) > length:
        raise CatalogError(422, 'invalid_field', f'{name} слишком длинное.')
    return text


def _fk_conflict(exc: Exception) -> CatalogError:
    text = str(exc)
    if 'foreign key' in text.lower() or 'foreign_key' in text.lower():
        return CatalogError(409, 'reference_in_use',
                            'Значение используется другими записями и не может быть удалено.')
    if 'unique' in text.lower() or 'duplicate key' in text.lower():
        return CatalogError(409, 'already_exists',
                            'Запись с такими ключевыми полями уже существует.')
    return CatalogError(502, 'catalog_db_error', f'Ошибка базы данных: {exc}')


# ------------------------------------------------------------------- services

def list_services() -> List[dict]:
    return _repo().list_services()


def create_service(code: str, name: str) -> dict:
    code = _required(code, 'код службы', 32)
    name = _required(name, 'название службы')
    repository = _repo()
    if repository.get_service(code) is not None:
        raise CatalogError(409, 'service_exists', f'Служба {code!r} уже существует.')
    return repository.create_service(code, name)


def update_service(code: str, name: str) -> dict:
    name = _required(name, 'название службы')
    repository = _repo()
    if repository.get_service(code) is None:
        raise CatalogError(404, 'service_not_found', f'Служба {code!r} не найдена.')
    updated = repository.update_service(code, name)
    if updated is None:
        raise CatalogError(404, 'service_not_found', f'Служба {code!r} не найдена.')
    return updated


def delete_service(code: str) -> None:
    repository = _repo()
    if repository.get_service(code) is None:
        raise CatalogError(404, 'service_not_found', f'Служба {code!r} не найдена.')
    try:
        repository.delete_service(code)
    except DbConnectionError as exc:
        raise _fk_conflict(exc) from None


# ---------------------------------------------------------------- categories

def list_categories() -> List[dict]:
    return _repo().list_categories()


def _category_id(value, name: str = 'идентификатор категории') -> int:
    try:
        return int(str(value or '').strip())
    except (TypeError, ValueError):
        raise CatalogError(422, 'invalid_field', f'{name} должен быть целым числом.') from None


def create_category(category_id, name: str) -> dict:
    category_id = _category_id(category_id)
    if not 1 <= category_id <= 999:
        raise CatalogError(422, 'invalid_field', 'Идентификатор категории вне диапазона 1..999.')
    name = _required(name, 'название категории')
    repository = _repo()
    if repository.get_category(category_id) is not None:
        raise CatalogError(409, 'category_exists', f'Категория {category_id} уже существует.')
    return repository.create_category(category_id, name)


def update_category(category_id, name: str) -> dict:
    category_id = _category_id(category_id)
    name = _required(name, 'название категории')
    repository = _repo()
    if repository.get_category(category_id) is None:
        raise CatalogError(404, 'category_not_found', f'Категория {category_id} не найдена.')
    updated = repository.update_category(category_id, name)
    if updated is None:
        raise CatalogError(404, 'category_not_found', f'Категория {category_id} не найдена.')
    return updated


def delete_category(category_id) -> None:
    category_id = _category_id(category_id)
    repository = _repo()
    if repository.get_category(category_id) is None:
        raise CatalogError(404, 'category_not_found', f'Категория {category_id} не найдена.')
    try:
        repository.delete_category(category_id)
    except DbConnectionError as exc:
        raise _fk_conflict(exc) from None


# -------------------------------------------------------------------- entries

def list_entries(category_id=None) -> List[dict]:
    cid = _category_id(category_id) if category_id is not None else None
    return _repo().list_entries(cid)


def _check_category(repository, category_id) -> None:
    if repository.get_category(category_id) is None:
        raise CatalogError(404, 'category_not_found',
                           f'Категория {category_id} не найдена.')


def _check_service(repository, service_code) -> None:
    if repository.get_service(service_code) is None:
        raise CatalogError(404, 'service_not_found',
                           f'Служба {service_code!r} не найдена.')


def create_entry(data: dict) -> dict:
    entry_id = _required(data.get('entry_id'), 'код записи', 64)
    category_id = _category_id(data.get('category_id'))
    title = str(data.get('title') or '').strip()
    repository = _repo()
    _check_category(repository, category_id)
    main_service_code = data.get('main_service_code')
    if main_service_code is not None and str(main_service_code).strip():
        main_service_code = str(main_service_code).strip()
        _check_service(repository, main_service_code)
    else:
        main_service_code = None
    if repository.get_entry(entry_id) is not None:
        raise CatalogError(409, 'entry_exists', f'Запись {entry_id!r} уже существует.')
    payload = {
        'id': entry_id,
        'category_id': category_id,
        'group_name': str(data.get('group_name') or ''),
        'statistical_group': str(data.get('statistical_group') or ''),
        'sign1': str(data.get('sign1') or ''),
        'sign2': str(data.get('sign2') or ''),
        'sign3': str(data.get('sign3') or ''),
        'extra_signs': str(data.get('extra_signs') or ''),
        'title': title,
        'ekp_type': str(data.get('ekp_type') or ''),
        'main_service_code': main_service_code,
    }
    return repository.create_entry(payload)


def update_entry(entry_id: str, data: dict) -> dict:
    entry_id = _required(entry_id, 'код записи', 64)
    repository = _repo()
    if repository.get_entry(entry_id) is None:
        raise CatalogError(404, 'entry_not_found', f'Запись {entry_id!r} не найдена.')
    payload = {}
    if 'category_id' in data and data['category_id'] is not None:
        category_id = _category_id(data['category_id'])
        _check_category(repository, category_id)
        payload['category_id'] = category_id
    for field in ('group_name', 'statistical_group', 'sign1', 'sign2', 'sign3',
                  'extra_signs', 'title', 'ekp_type'):
        if field in data:
            payload[field] = str(data[field] or '')
    if 'main_service_code' in data:
        main = data['main_service_code']
        if main is not None and str(main).strip():
            main = str(main).strip()
            _check_service(repository, main)
        else:
            main = None
        payload['main_service_code'] = main
    updated = repository.update_entry(entry_id, payload)
    if updated is None:
        raise CatalogError(404, 'entry_not_found', f'Запись {entry_id!r} не найдена.')
    return updated


def delete_entry(entry_id: str) -> None:
    entry_id = _required(entry_id, 'код записи', 64)
    repository = _repo()
    if repository.get_entry(entry_id) is None:
        raise CatalogError(404, 'entry_not_found', f'Запись {entry_id!r} не найдена.')
    repository.delete_entry(entry_id)


# ------------------------------------------------------------ entry-services

def list_entry_services(entry_id=None, service_code=None) -> List[dict]:
    return _repo().list_entry_services(entry_id, service_code)


def _entry_service_id(value) -> int:
    try:
        return int(str(value or '').strip())
    except (TypeError, ValueError):
        raise CatalogError(422, 'invalid_field', 'Идентификатор связи должен быть целым числом.') from None


def create_entry_service(data: dict) -> dict:
    entry_id = _required(data.get('entry_id'), 'код записи', 64)
    service_code = _required(data.get('service_code'), 'код службы', 32)
    repository = _repo()
    if repository.get_entry(entry_id) is None:
        raise CatalogError(404, 'entry_not_found', f'Запись {entry_id!r} не найдена.')
    _check_service(repository, service_code)
    payload = {
        'entry_id': entry_id,
        'service_code': service_code,
        'condition_type': str(data.get('condition_type') or 'column'),
        'condition_text': str(data.get('condition_text') or ''),
        'value': str(data.get('value') or ''),
        'is_main': bool(data.get('is_main')),
    }
    try:
        return repository.create_entry_service(payload)
    except DbConnectionError as exc:
        raise _fk_conflict(exc) from None


def update_entry_service(item_id, data: dict) -> dict:
    item_id = _entry_service_id(item_id)
    repository = _repo()
    if repository.get_entry_service(item_id) is None:
        raise CatalogError(404, 'link_not_found', f'Связь {item_id} не найдена.')
    payload = {}
    if 'service_code' in data:
        service_code = _required(data['service_code'], 'код службы', 32)
        _check_service(repository, service_code)
        payload['service_code'] = service_code
    for field in ('condition_type', 'condition_text', 'value'):
        if field in data:
            payload[field] = str(data[field] or '')
    if 'is_main' in data:
        payload['is_main'] = bool(data['is_main'])
    updated = repository.update_entry_service(item_id, payload)
    if updated is None:
        raise CatalogError(404, 'link_not_found', f'Связь {item_id} не найдена.')
    return updated


def delete_entry_service(item_id) -> None:
    item_id = _entry_service_id(item_id)
    repository = _repo()
    if repository.get_entry_service(item_id) is None:
        raise CatalogError(404, 'link_not_found', f'Связь {item_id} не найдена.')
    repository.delete_entry_service(item_id)


# --------------------------------------------------------------- geo-addresses

def list_geo_addresses(kind=None, limit=None) -> List[dict]:
    if kind is not None and str(kind).strip() not in ('building', 'street'):
        raise CatalogError(422, 'invalid_field', 'kind должен быть building или street.')
    limit_value = None
    if limit is not None:
        limit_value = int(str(limit))
        if not 1 <= limit_value <= 10000:
            raise CatalogError(422, 'invalid_field', 'limit вне диапазона 1..10000.')
    return _repo().list_geo_addresses(str(kind).strip() if kind else None, limit_value)


def _number(value, name: str) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise CatalogError(422, 'invalid_field', f'{name} должен быть числом.') from None


def create_geo_address(data: dict) -> dict:
    address_id = _required(data.get('address_id'), 'идентификатор адреса', 64)
    street = _required(data.get('street'), 'улицу')
    repository = _repo()
    if repository.get_geo_address(address_id) is not None:
        raise CatalogError(409, 'address_exists', f'Адрес {address_id!r} уже существует.')
    payload = {
        'id': address_id,
        'street': street,
        'house': str(data.get('house') or ''),
        'lat': _number(data.get('lat'), 'lat'),
        'lon': _number(data.get('lon'), 'lon'),
        'kind': str(data.get('kind') or 'building'),
        'point': data.get('point'),
    }
    return repository.create_geo_address(payload)


def update_geo_address(address_id: str, data: dict) -> dict:
    address_id = _required(address_id, 'идентификатор адреса', 64)
    repository = _repo()
    if repository.get_geo_address(address_id) is None:
        raise CatalogError(404, 'address_not_found', f'Адрес {address_id!r} не найден.')
    payload = {}
    if 'street' in data:
        payload['street'] = _required(data['street'], 'улицу')
    for field in ('house', 'kind'):
        if field in data:
            payload[field] = str(data[field] or '')
    if 'lat' in data:
        payload['lat'] = _number(data['lat'], 'lat')
    if 'lon' in data:
        payload['lon'] = _number(data['lon'], 'lon')
    if 'point' in data:
        payload['point'] = data['point']
    updated = repository.update_geo_address(address_id, payload)
    if updated is None:
        raise CatalogError(404, 'address_not_found', f'Адрес {address_id!r} не найден.')
    return updated


def delete_geo_address(address_id: str) -> None:
    address_id = _required(address_id, 'идентификатор адреса', 64)
    repository = _repo()
    if repository.get_geo_address(address_id) is None:
        raise CatalogError(404, 'address_not_found', f'Адрес {address_id!r} не найден.')
    repository.delete_geo_address(address_id)