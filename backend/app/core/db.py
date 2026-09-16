from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.base import Base

# Импорт ради регистрации моделей в метаданных Base.
from app.models import training, user  # noqa: F401

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def create_all() -> None:
    """Создаёт схему напрямую, минуя миграции.

    Используется только в тестах на временной базе. Рабочая схема
    приводится в порядок через scripts/migrate.py, иначе обновление
    приложения теряло бы данные.
    """
    Base.metadata.create_all(engine)
