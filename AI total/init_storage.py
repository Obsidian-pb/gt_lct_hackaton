"""CLI for the storage layer (Этап 5: переключение репозитория).

Modes:
  python init_storage.py --check           read-only state (mode, schema, counts)
  python init_storage.py --init            apply schema 2.5.0
  python init_storage.py --mirror          one-time sync: JSON files -> DB
                                           (delegates to training-data import)
  python init_storage.py --self-test       live round-trip against PostgreSQL
  python init_storage.py --pause           keep the console open on Windows

Exit codes: 0 = OK, 2 = problem (like data_layer/init_auth/init_catalog).
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

from db_connection import quote_literal as q
from storage_config import get_storage_config
from storage_repository import SCHEMA_VERSION, StorageRepository

EXIT_OK, EXIT_FAIL = 0, 2


def _log(message: str) -> None:
    print('[STORAGE] ' + message, flush=True)


def cmd_check() -> int:
    config = get_storage_config()
    _log(f'Режим хранилища: «{config["mode"]}».')
    if config['mode'] == 'files':
        _log('ОШИБКА: режим files отключён; для запуска требуется PostgreSQL.')
        return EXIT_FAIL
    repo = StorageRepository()
    version = repo.migration_version()
    if not version:
        _log('ОШИБКА: схема ' + SCHEMA_VERSION + ' не установлена. Выполните --init.')
        return EXIT_FAIL
    counts = repo.counts()
    _log('Схема: ' + str(version))
    _log('Таблицы: tasks=%d sessions=%d scenarios=%d trainings=%d materials=%d workshop=%d'
         % (counts['task'], counts['session'], counts['scenario'],
            counts['training'], counts['material'], counts['workshop_card']))
    return EXIT_OK


def cmd_init() -> int:
    repo = StorageRepository()
    try:
        repo.ensure_schema()
    except Exception as exc:  # noqa: BLE001 - CLI should report and fail
        _log('ОШИБКА: ' + str(exc))
        return EXIT_FAIL
    _log('Схема ' + SCHEMA_VERSION
         + ' установлена (workshop_card.content jsonb добавлена).')
    return EXIT_OK


def cmd_mirror(directory: str | None) -> int:
    """One-time pre-switch sync: JSON learning data -> PostgreSQL."""
    _log('Первичная синхронизация файлы → БД…')
    import training_data_service
    try:
        result = training_data_service.import_all(directory)
    except training_data_service.TrainingDataError as exc:
        _log('ОШИБКА: ' + str(exc))
        _log('Импорт не выполнен. Проверьте наличие t-*.json / s-*.json / curriculum/*.json.')
        return EXIT_FAIL
    _log('Импортировано: ' + ', '.join(f'{key}={value}' for key, value in
                                        sorted(result['counts'].items())
                                        if value))
    if result['warnings']:
        _log('Предупреждения: ' + '; '.join(result['warnings'][:10]))
    return EXIT_OK


def cmd_self_test() -> int:
    """Round-trip a temporary task and session through the live database."""
    if get_storage_config()['mode'] == 'files':
        _log('ОШИБКА: самопроверка требует режима files-to-db или db-only.')
        return EXIT_FAIL
    repo = StorageRepository()
    suffix = uuid.uuid4().hex[:12]
    task_id = 't-' + suffix
    session_id = 's-' + suffix
    task_doc = {
        'id': task_id, 'title': 'Самопроверка', 'status': 'approved',
        'workflow': 'caller', 'level': 'medium', 'opening': 'Тест',
        'persona': 'Тест', 'fields': {}, 'source': 'self-test',
        'created_at': None, 'updated_at': None,
    }
    session_doc = {
        'id': session_id, 'student': 'self-test', 'status': 'active',
        'task': task_doc, 'reference_hash': '0' * 64,
        'card': {}, 'history': [{'id': 1, 'role': 'caller', 'text': 'Тест'}],
        'hints': [], 'card_edits': [], 'training_reveals': [],
        'training': None, 'created_at': None, 'updated_at': None,
    }
    try:
        repo.upsert_task(task_doc)
        repo.upsert_session(session_doc)
        loaded_task = repo.load_task(task_id)
        loaded_session = repo.load_session(session_id)
        assert loaded_task['id'] == task_id, 'task id mismatch'
        assert loaded_session['id'] == session_id, 'session id mismatch'
        assert loaded_session['student'] == 'self-test', 'student name mismatch'
        assert loaded_session['history'][0]['text'] == 'Тест', 'history mismatch'
        _log('Самопроверка: round-trip task и session прошёл на живой БД.')
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001 - CLI reports failures
        _log('ОШИБКА самопроверки: ' + str(exc))
        return EXIT_FAIL
    finally:
        with repo._connect() as connection:
            connection.execute('DELETE FROM "session" WHERE id = ' + q(session_id))
            connection.execute('DELETE FROM task WHERE id = ' + q(task_id))


def main() -> int:
    parser = argparse.ArgumentParser(description='Слой хранилища PostgreSQL (Этап 5)')
    parser.add_argument('--init', action='store_true', help='Установить схему 2.5.0')
    parser.add_argument('--check', action='store_true', help='Состояние хранилища')
    parser.add_argument('--mirror', action='store_true',
                        help='Первичная синхронизация файлы → БД')
    parser.add_argument('--self-test', action='store_true',
                        help='Живой round-trip task/session')
    parser.add_argument('--dir', help='Каталог данных для --mirror')
    parser.add_argument('--pause', action='store_true',
                        help='Ожидать Enter перед закрытием (Windows)')
    args = parser.parse_args()

    code = EXIT_OK
    if args.init:
        code = max(code, cmd_init())
    if args.mirror:
        code = max(code, cmd_mirror(args.dir))
    if args.check:
        code = max(code, cmd_check())
    if args.self_test:
        code = max(code, cmd_self_test())
    if not any((args.init, args.check, args.mirror, args.self_test)):
        parser.print_help()
        code = EXIT_FAIL
    if args.pause and os.name == 'nt':
        input('Нажмите Enter для закрытия…')
    return code


if __name__ == '__main__':
    sys.exit(main())