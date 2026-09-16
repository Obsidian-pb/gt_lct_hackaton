"""Приведение схемы базы к актуальному состоянию.

Запускается при старте контейнера перед приложением.

Отдельно обрабатывается база, созданную прежним способом — через
`Base.metadata.create_all`. В ней таблицы есть, но alembic об этом не знает
и попытается создать их заново. Поэтому такую базу сначала помечаем как
находящуюся на исходной миграции, и дальше она обновляется обычным порядком.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        # Таблица alembic_version может существовать, но быть пустой, поэтому
        # ориентируемся на саму запись о ревизии, а не на наличие таблицы.
        revision = MigrationContext.configure(connection).get_current_revision()

    if revision is None and "app_user" in tables:
        print("База создана до появления миграций — отмечаю исходную ревизию.")
        command.stamp(config, "head")
        return

    command.upgrade(config, "head")
    print("Схема базы актуальна.")


if __name__ == "__main__":
    main()
