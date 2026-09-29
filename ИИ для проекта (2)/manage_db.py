"""PostgreSQL schema management and explicit legacy import for trainer 112."""
import argparse
import json
import os
from pathlib import Path
import sqlite3

from database import PostgresStore, SCHEMA_VERSION


def _dsn(args):
    value = args.database_url or os.environ.get('DATABASE_URL')
    if not value:
        raise SystemExit('DATABASE_URL не задан. Пример: postgresql://trainer:password@127.0.0.1:5432/trainer112')
    return value


def migrate(store):
    version = store.migrate()
    print(f'PostgreSQL schema ready: v{version}')


def status(store):
    print(json.dumps(store.health(), ensure_ascii=False, indent=2))


def import_legacy(store, data_dir: Path, merge=False):
    store.migrate()
    summary = {'users':0,'engine_items':0,'curriculum':0,'materials':0}
    with store.connect() as conn:
        counts = {
            'users': conn.execute('SELECT count(*) AS n FROM app_users').fetchone()['n'],
            'engine': conn.execute('SELECT count(*) AS n FROM engine_items').fetchone()['n'],
            'curriculum': conn.execute('SELECT count(*) AS n FROM curriculum_resources').fetchone()['n'],
            'materials': conn.execute('SELECT count(*) AS n FROM materials').fetchone()['n'],
        }
    if not merge and any(counts.values()):
        raise SystemExit('База уже содержит данные. Для осознанного объединения используйте --merge.')

    accounts_path = data_dir / 'accounts.sqlite3'
    if accounts_path.exists():
        db = sqlite3.connect(accounts_path)
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute('SELECT id,login,full_name,role,salt,password_hash,active,created_at FROM users ORDER BY id').fetchall()
            with store.connect() as conn:
                for row in rows:
                    conn.execute('''INSERT INTO app_users(login,full_name,role,salt,password_hash,active,created_at,updated_at)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                                    ON CONFLICT(login) DO NOTHING''',
                                 (row['login'], row['full_name'], row['role'], bytes(row['salt']), bytes(row['password_hash']),
                                  bool(row['active']), row['created_at'], row['created_at']))
                    summary['users'] += 1
        finally:
            db.close()

    for path in sorted(data_dir.glob('[ts]-*.json')):
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
            store.save_engine_item(item)
            summary['engine_items'] += 1
        except Exception as exc:
            raise SystemExit(f'Не удалось импортировать {path.name}: {exc}') from exc

    curriculum_dir = data_dir / 'curriculum'
    if curriculum_dir.exists():
        for path in sorted(curriculum_dir.glob('scenario-*.json')) + sorted(curriculum_dir.glob('training-*.json')):
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                store.save_curriculum(item)
                summary['curriculum'] += 1
            except Exception as exc:
                raise SystemExit(f'Не удалось импортировать {path.name}: {exc}') from exc
        materials_path = curriculum_dir / 'materials.json'
        if materials_path.exists():
            try:
                rows = json.loads(materials_path.read_text(encoding='utf-8'))
                for item in rows:
                    store.add_material(item)
                    summary['materials'] += 1
            except Exception as exc:
                raise SystemExit(f'Не удалось импортировать materials.json: {exc}') from exc

    print(json.dumps({'imported':summary,'database':store.health()}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='PostgreSQL для общего сервера тренажёра 112')
    parser.add_argument('--database-url')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate')
    sub.add_parser('status')
    imp = sub.add_parser('import-legacy')
    imp.add_argument('--data-dir', default=str(Path(__file__).with_name('data')))
    imp.add_argument('--merge', action='store_true', help='Разрешить объединение с уже заполненной БД')
    args = parser.parse_args()
    store = PostgresStore(_dsn(args))
    if args.command == 'migrate':
        migrate(store)
    elif args.command == 'status':
        status(store)
    else:
        import_legacy(store, Path(args.data_dir), args.merge)


if __name__ == '__main__':
    main()
