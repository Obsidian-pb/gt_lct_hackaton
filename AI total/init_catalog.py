"""Initialize the catalog layer: schema 2.2.0 and static reference imports.

Этап 2.2: создаёт таблицы раздела 2 документа database_structure.qmd
(справочники, мастерская карточек, учебный каталог, сценарии/тренировки,
сессии/оценивание, служебные), импортирует классификатор происшествий из
catalog/classifier.json и, по флагу --geo, адреса OSM из ui/geo/addresses.json.

Run manually (TEST_CATALOG.cmd) or by START_ALL.ps1.
Exit codes: 0 = ok, 2 = failure (same convention as data_layer.py/init_auth.py).
"""
from __future__ import annotations

import argparse
import sys

import catalog_importer
import catalog_repository

EXPECTED = {'services': 61, 'categories': 24, 'entries': 1283}


def run_init(import_geo: bool = False) -> tuple:
    """Create the schema and import the classifier (idempotent)."""
    try:
        repository = catalog_repository.CatalogRepository()
        repository.ensure_schema()
        data = catalog_importer.parse_classifier()
        imported = repository.replace_classifier(
            data['services'], data['categories'],
            data['entries'], data['entry_services'])
        message = (f'Схема {catalog_repository.SCHEMA_VERSION} создана; классификатор: '
                   f'службы={imported["services"]}, категории={imported["categories"]}, '
                   f'записи={imported["entries"]}, связи={imported["entry_services"]}.')
        if import_geo:
            geo = catalog_importer.parse_geo_addresses()
            imported_geo = repository.replace_geo(geo['addresses'], geo['buildings'])
            message += (f' Geo: адреса={imported_geo["addresses"]}, '
                        f'здания={imported_geo["buildings"]}.')
    except Exception as exc:
        return False, f'Не удалось инициализировать слой справочников: {exc}'
    return True, message


def run_check() -> tuple:
    """Verify schema presence and reference row counts without writing."""
    try:
        repository = catalog_repository.CatalogRepository()
        version = repository.migration_version()
        counts = repository.counts()
    except Exception as exc:
        return False, f'Ошибка проверки слоя справочников: {exc}'
    if version is None:
        return False, f'Схема {catalog_repository.SCHEMA_VERSION} не инициализирована.'
    problems = []
    for key, expected in EXPECTED.items():
        if counts[key] != expected:
            problems.append(f'{key}={counts[key]} (ожидается {expected})')
    if counts['entry_services'] <= 0:
        problems.append(f'entry_services={counts["entry_services"]} (ожидается > 0)')
    counts_text = ', '.join(f'{key}={counts[key]}' for key in
                            ('services', 'categories', 'entries', 'entry_services'))
    if problems:
        return False, f'Слой справочников готов (схема {version}), но количества не совпали: ' \
                      + ', '.join(problems)
    return True, f'Слой справочников готов: схема {version}; {counts_text}.'


def run_self_test() -> tuple:
    """Read a small sample from every reference table through the CRUD layer."""
    try:
        repository = catalog_repository.CatalogRepository()
        checks = [
            ('службы', repository.list_services()),
            ('категории', repository.list_categories()),
            ('записи', repository.list_entries()),
            ('связи', repository.list_entry_services()),
            ('гео-адреса', repository.list_geo_addresses()),
            ('здания', repository.list_geo_buildings()),
        ]
        empty = [label for label, rows in checks if not rows]
        if empty:
            return False, 'Самопроверка не пройдена: пустые таблицы — ' + ', '.join(empty)
    except Exception as exc:
        return False, f'Самопроверка слоя справочников не пройдена: {exc}'
    return True, 'Чтение выборки из всех таблиц справочников через CRUD-методы прошло.'


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description='Инициализация слоя справочников (Этап 2.2)')
    parser.add_argument('--init', action='store_true',
                        help='Создать схему и импортировать классификатор (по умолчанию)')
    parser.add_argument('--geo', action='store_true',
                        help='Дополнительно импортировать гео-адреса из ui/geo/addresses.json')
    parser.add_argument('--check', action='store_true', help='Проверить состояние слоя')
    parser.add_argument('--self-test', action='store_true',
                        help='Прочитать выборку из каждой таблицы справочников')
    parser.add_argument('--pause', action='store_true',
                        help='Ждать Enter перед выходом (для отдельного окна)')
    args = parser.parse_args(argv)

    steps = []
    if args.check:
        steps.append(('Проверка', run_check))
    if args.init:
        steps.append(('Инициализация', lambda: run_init(args.geo)))
    if args.self_test:
        steps.append(('Самопроверка', run_self_test))
    if not (args.init or args.check or args.self_test):
        steps.append(('Инициализация', lambda: run_init(args.geo)))

    ok_all = True
    for label, step in steps:
        ok, message = step()
        ok_all = ok_all and ok
        print(f'[CATALOG] {label}: {message}' if ok
              else f'[CATALOG] {label}: ОШИБКА: {message}')

    if args.pause:
        try:
            input('\nНажмите Enter для выхода...')
        except (EOFError, KeyboardInterrupt):
            pass
    return 0 if ok_all else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))