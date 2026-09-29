"""Provision shared-server accounts without putting passwords in shell history."""
import argparse
from getpass import getpass
import os
from pathlib import Path

from database import store_from_url
from shared_auth import Accounts, ROLES


def _load_env_file(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def main():
    # CLI commands are often started from a fresh PowerShell window.
    # Load the shared-server DSN automatically so `manage_users.py create ...`
    # never creates a local SQLite account by accident.
    _load_env_file(Path(__file__).with_name('.env.server'))
    parser = argparse.ArgumentParser(description='Учётные записи общего сервера тренажёра 112')
    parser.add_argument('--data-dir', default=str(Path(__file__).with_name('data')))
    parser.add_argument('--database-url', help='PostgreSQL DSN; по умолчанию DATABASE_URL')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('login')
    create.add_argument('full_name')
    create.add_argument('role', choices=sorted(ROLES))
    commands.add_parser('bootstrap-admin', help='Создать первого администратора, если база пуста')
    commands.add_parser('list')
    update = commands.add_parser('update')
    update.add_argument('user_id', type=int)
    update.add_argument('--role', choices=sorted(ROLES))
    update.add_argument('--name')
    active = update.add_mutually_exclusive_group()
    active.add_argument('--enable', action='store_true')
    active.add_argument('--disable', action='store_true')
    passwd = commands.add_parser('password')
    passwd.add_argument('user_id', type=int)
    args = parser.parse_args()

    dsn = args.database_url if args.database_url is not None else os.environ.get('DATABASE_URL')
    store = store_from_url(dsn, auto_migrate=True) if dsn else None
    accounts = Accounts(args.data_dir, store)
    if args.command == 'list':
        for user in accounts.list_users():
            print(f"{user['id']}\t{user['login']}\t{user['full_name']}\t{user['role']}\t{'active' if user['active'] else 'disabled'}")
        return
    if args.command == 'update':
        enabled = True if args.enable else False if args.disable else None
        user = accounts.update(args.user_id, role=args.role, active=enabled, full_name=args.name)
        print(f"Обновлено: {user['login']} / {user['full_name']} / {user['role']}")
        return
    if args.command == 'password':
        password = getpass('Новый пароль (минимум 10 символов): ')
        if password != getpass('Повторите пароль: '):
            raise SystemExit('Пароли не совпадают.')
        accounts.set_password(args.user_id, password)
        print('Пароль обновлён.')
        return
    if args.command == 'bootstrap-admin':
        if accounts.count():
            print('Учётные записи уже существуют; создание первого администратора не требуется.')
            return
        args.login, args.full_name, args.role = 'admin', 'Администратор', 'admin'
    if accounts.count() and args.role == 'admin':
        print('Создание ещё одного администратора выполняйте только на доверенном сервере.')
    password = getpass('Пароль (минимум 10 символов): ')
    if password != getpass('Повторите пароль: '):
        raise SystemExit('Пароли не совпадают.')
    user = accounts.create(args.login, args.full_name, args.role, password)
    print(f"Учётная запись создана: id={user['id']} login={user['login']}")


if __name__ == '__main__':
    main()
