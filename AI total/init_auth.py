"""Initialize the auth layer: schema, seeded administrator and login self-test.

Этап 2.1: создаёт таблицы пользователей/аутентификации, посеивает учётную
запись администратора (по умолчанию admin/admin123) и, по запросу, прогоняет
полный цикл входа. Запускается вручную (TEST_AUTH.cmd) и лаунчером START_ALL.ps1.

Exit codes: 0 = ok, 2 = failure (same convention as data_layer.py).
"""
from __future__ import annotations

import argparse
import sys

import auth_crypto
import auth_repository
import auth_service


def run_init() -> tuple:
    """Create the schema and seed the administrator; idempotent."""
    try:
        repository = auth_repository.AuthRepository()
        repository.ensure_schema()
        admin = auth_service.seed_admin()
        login, password = auth_crypto.admin_credentials()
    except Exception as exc:
        return False, f'Не удалось инициализировать слой аутентификации: {exc}'
    return (True, f'Схема {auth_repository.SCHEMA_VERSION} создана; администратор '
                  f'{login!r} готов (id={admin["id"]}, пароль={password!r}).')


def run_check() -> tuple:
    """Verify schema presence and the seeded administrator without writing."""
    try:
        repository = auth_repository.AuthRepository()
        version = repository.migration_version()
        login, _password = auth_crypto.admin_credentials()
        admin = repository.find_by_login(login)
    except Exception as exc:
        return False, f'Ошибка проверки слоя аутентификации: {exc}'
    if version is None:
        return False, f'Схема {auth_repository.SCHEMA_VERSION} не инициализирована.'
    if admin is None or not admin['is_active']:
        return False, f'Администратор {login!r} отсутствует или деактивирован.'
    return (True, f'Слой аутентификации готов: схема {version}, '
                  f'пользователей в БД: {repository.count_users()}.')


def run_self_test() -> tuple:
    """Full cycle: login -> me -> refresh -> logout under the admin account."""
    try:
        login, password = auth_crypto.admin_credentials()
        pair = auth_service.login(login, password, 'init-auth-self-test')
        user = auth_service.authenticate_access_token('Bearer ' + pair['access_token'])
        if user['id'] != pair['user']['id']:
            raise RuntimeError('Идентификатор из /auth/me не совпадает с токеном.')
        refreshed = auth_service.refresh(pair['refresh_token'], 'init-auth-self-test')
        auth_service.logout(refreshed['refresh_token'])
    except auth_service.AuthError as exc:
        return False, f'Самопроверка входа не пройдена: {exc.message}'
    except Exception as exc:
        return False, f'Самопроверка входа не пройдена: {exc}'
    return True, 'Вход администратора пройден полностью: login → me → refresh → logout.'


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description='Инициализация слоя пользователей и аутентификации')
    parser.add_argument('--init', action='store_true', help='Создать схему и посеять администратора (по умолчанию)')
    parser.add_argument('--check', action='store_true', help='Проверить состояние слоя')
    parser.add_argument('--self-test', action='store_true', help='Прогнать полный цикл входа администратора')
    parser.add_argument('--pause', action='store_true', help='Ждать Enter перед выходом (для отдельного окна)')
    args = parser.parse_args(argv)

    steps = []
    if args.check:
        steps.append(('Проверка', run_check))
    if args.init:
        steps.append(('Инициализация', run_init))
    if args.self_test:
        steps.append(('Самопроверка входа', run_self_test))
    if not (args.init or args.check or args.self_test):
        steps.append(('Инициализация', run_init))

    ok_all = True
    for label, step in steps:
        ok, message = step()
        ok_all = ok_all and ok
        print(f'[AUTH] {label}: {message}' if ok else f'[AUTH] {label}: ОШИБКА: {message}')

    if args.pause:
        try:
            input('\nНажмите Enter для выхода...')
        except (EOFError, KeyboardInterrupt):
            pass
    return 0 if ok_all else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))