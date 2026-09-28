"""Data layer startup check for PostgreSQL.

Launched alongside the application (see START_ALL.ps1) and run standalone via
TEST_DB.cmd. The current scope is intentionally minimal: open and verify a
database connection and report the result to the console. No queries or data
logic are performed yet.

Exit codes: 0 = connected, 2 = not connected, 3 = misconfigured.
"""
from __future__ import annotations

import argparse
import sys

import db_config
import db_connection


def run_check() -> tuple[bool, str]:
    """Try to connect and verify the database. Return (ok, human_message)."""
    try:
        config = db_config.get_db_config()
    except Exception as exc:  # configuration could not be resolved
        return False, f'Не удалось прочитать настройки БД: {exc}'

    target = f'{config.get("host")}:{config.get("port")}/{config.get("dbname")}'
    connection = None
    try:
        connection = db_connection.connect_from_config(config)
        version = connection.server_params.get('server_version', 'неизвестно')
        mode = 'SSL' if connection.ssl_active else 'без SSL'
        auth = connection.auth_method
    except db_connection.DbConnectionError as exc:
        return False, f'{exc} [{target}]'
    except Exception as exc:  # any unexpected protocol/socket failure
        return False, f'Непредвиденная ошибка подключения: {exc} [{target}]'
    else:
        return True, f'БД подключена: {target} ({mode}, auth={auth}, сервер {version})'
    finally:
        if connection is not None:
            connection.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Проверка подключения к PostgreSQL')
    parser.add_argument('--pause', action='store_true', help='Ждать Enter перед выходом (для отдельного окна)')
    args = parser.parse_args(argv)

    ok, message = run_check()
    if ok:
        print(f'[DATA] {message}')
        code = 0
    else:
        print(f'[DATA] БД НЕ подключена: {message}')
        code = 2

    if args.pause:
        try:
            input('\nНажмите Enter для выхода...')
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
