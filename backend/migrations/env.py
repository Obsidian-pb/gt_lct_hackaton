"""Окружение alembic.

Адрес базы берётся из настроек приложения, а не из alembic.ini: иначе он
задавался бы в двух местах и рано или поздно разошёлся бы. Метаданные —
те же, что использует приложение, поэтому автогенерация видит все модели.
"""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402

# Импорт ради регистрации моделей в метаданных.
from app.models import audit, training, user  # noqa: E402,F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Иначе смена типа колонки не попадёт в автогенерацию.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
