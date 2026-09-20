from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.base import Base

# Импорт ради регистрации моделей в метаданных Base.
from app.models import audit, training, user  # noqa: F401

_settings = get_settings()

# Размер пула подобран по замеру, а не на глаз. При умолчаниях SQLAlchemy
# (5 соединений плюс 10 сверх) сотня одновременных пользователей — норматив
# технического задания — упиралась в пул: запросы ждали по тридцать секунд
# и часть падала с QueuePool timeout. Синхронные обработчики FastAPI
# выполняются в пуле потоков, поэтому соединений нужно не меньше, чем потоков.
#
# Ограничение сверху — max_connections самого PostgreSQL (по умолчанию 100);
# при добавлении узлов приложения значения нужно пересчитать, отсюда настройка.
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_pool_overflow,
    # Ждать соединения полминуты бессмысленно: обучающийся за это время
    # уже нарушит норматив. Лучше быстро ответить ошибкой.
    pool_timeout=_settings.db_pool_timeout_seconds,
)
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
