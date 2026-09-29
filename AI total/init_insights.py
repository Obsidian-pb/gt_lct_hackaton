"""Read-only readiness check for the cached analytics layer."""
from __future__ import annotations

import argparse
import sys

from storage_config import get_storage_config
from storage_repository import SCHEMA_VERSION, StorageRepository

EXIT_OK, EXIT_FAIL = 0, 2


def run_check() -> tuple[bool, str]:
    config = get_storage_config()
    if config['mode'] == 'files':
        return False, 'Проверка аналитики требует PostgreSQL.'
    try:
        repository = StorageRepository()
        version = repository.migration_version()
        source_updated_at, works, _counts = repository.insight_source()
    except Exception as exc:
        return False, f'Проверка аналитического слоя не выполнена: {exc}'
    if version != SCHEMA_VERSION:
        return False, f'Схема storage {SCHEMA_VERSION} не инициализирована.'
    state = 'есть данные для отчёта' if works else 'пока нет проверенных работ'
    return True, (f'Аналитический слой доступен: storage {version}; {state}; '
                  f'последнее изменение={source_updated_at or "нет"}.')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Проверка аналитического кэша')
    parser.add_argument('--check', action='store_true', help='Проверить доступность и схему')
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return EXIT_FAIL
    ok, message = run_check()
    print('[INSIGHTS] ' + message if ok else '[INSIGHTS] ОШИБКА: ' + message)
    return EXIT_OK if ok else EXIT_FAIL


if __name__ == '__main__':
    sys.exit(main())
