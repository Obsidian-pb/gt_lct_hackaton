"""Настройки комплекса, которыми администратор управляет из интерфейса.

Комплекс должен работать и в изолированном контуре с локальной моделью,
и с внешним API. До сих пор контур переключался только правкой `.env`
и перезапуском контейнера, а у администратора учебного комплекса есть
один инструмент — браузер. Поэтому действующие значения читаются отсюда,
а не напрямую из переменных окружения.

Порядок старшинства: значение из базы главнее переменной окружения.
Переменные задают начальное состояние при первом запуске, дальше
комплексом управляет администратор (см. докстринг `SystemSetting`).

Ключ доступа к модели лежит в той же таблице открытым текстом: доступ
к базе и так означает доступ к серверу, где ключ лежал бы в `.env` рядом.
Наружу, в API, он не отдаётся ни при каких обстоятельствах — только
признак «задан».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.audit import SystemSetting
from app.models.user import User

logger = logging.getLogger(__name__)

LLM_KEY = "llm"
LOGGING_KEY = "logging"

# Провайдеры, между которыми переключается комплекс. Список закрытый:
# каждое значение поддержано кодом сборки провайдера.
PROVIDERS = ("stub", "local", "openai", "gigachat")

# Ниже шести месяцев глубину хранения задать нельзя: ТЗ требует хранить
# журнал безопасности не менее полугода. Ограничение проверяется здесь,
# а не только в интерфейсе, — правку можно послать и мимо него.
MIN_AUDIT_RETENTION_DAYS = 180
MAX_AUDIT_RETENTION_DAYS = 3650

LOG_LEVELS = ("ERROR", "WARNING", "INFO", "DEBUG")


@dataclass(frozen=True)
class LlmConfig:
    """Действующая настройка языковой модели."""

    provider: str
    base_url: str
    model: str
    api_key: str
    disable_thinking: bool
    timeout_seconds: float

    def fingerprint(self) -> tuple:
        """Отпечаток настройки: по нему видно, что провайдера пора пересобрать.

        Сравнивается именно всё, что попадает в HTTP-клиент, — иначе смена
        только адреса или только ключа осталась бы незамеченной.
        """
        return (
            self.provider,
            self.base_url,
            self.model,
            self.api_key,
            self.disable_thinking,
            self.timeout_seconds,
        )


@dataclass(frozen=True)
class LoggingConfig:
    """Действующие параметры журналирования."""

    audit_retention_days: int
    level: str


@dataclass(frozen=True)
class Authorship:
    """Кто и когда правил настройку. Пусто, если её ни разу не меняли."""

    at: datetime | None = None
    by: str | None = None


def env_llm_config(provider: str | None = None) -> LlmConfig:
    """Начальное состояние из переменных окружения для выбранного провайдера.

    У GigaChat собственная пара переменных: адрес задан самим сервисом,
    а ключ и имя модели живут в отдельных полях настроек. Поэтому умолчания
    зависят от провайдера — иначе при переключении на GigaChat подставился бы
    адрес OpenAI.
    """
    settings = get_settings()
    provider = provider or settings.llm_provider
    if provider == "gigachat":
        return LlmConfig(
            provider=provider,
            base_url="",
            model=settings.gigachat_model,
            api_key=settings.gigachat_auth_key,
            disable_thinking=False,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return LlmConfig(
        provider=provider,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        disable_thinking=settings.llm_disable_thinking,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def env_logging_config() -> LoggingConfig:
    settings = get_settings()
    return LoggingConfig(
        audit_retention_days=max(settings.audit_retention_days, MIN_AUDIT_RETENTION_DAYS),
        level=settings.log_level.upper(),
    )


def stored_value(db: Session, key: str) -> dict:
    """Сырое значение настройки из базы; пустой словарь, если её не задавали."""
    row = db.get(SystemSetting, key)
    if row is None or not isinstance(row.value, dict):
        return {}
    return dict(row.value)


def authorship(db: Session, key: str) -> Authorship:
    row = db.get(SystemSetting, key)
    if row is None:
        return Authorship()
    return Authorship(at=row.updated_at, by=row.updated_by.login if row.updated_by else None)


def _pick(stored: dict, key: str, default):
    """Значение из базы, если оно задано, иначе из окружения.

    Отсутствие ключа и `null` обрабатываются одинаково: настройку могли
    записать раньше, когда поля ещё не было.
    """
    value = stored.get(key)
    return default if value is None else value


def llm_config(db: Session) -> LlmConfig:
    """Действующая настройка модели: запись в базе поверх окружения."""
    stored = stored_value(db, LLM_KEY)
    provider = str(_pick(stored, "provider", get_settings().llm_provider))
    fallback = env_llm_config(provider)
    return LlmConfig(
        provider=provider,
        base_url=str(_pick(stored, "base_url", fallback.base_url)),
        model=str(_pick(stored, "model", fallback.model)),
        api_key=str(_pick(stored, "api_key", fallback.api_key)),
        disable_thinking=bool(_pick(stored, "disable_thinking", fallback.disable_thinking)),
        timeout_seconds=float(_pick(stored, "timeout_seconds", fallback.timeout_seconds)),
    )


def logging_config(db: Session) -> LoggingConfig:
    stored = stored_value(db, LOGGING_KEY)
    fallback = env_logging_config()
    return LoggingConfig(
        audit_retention_days=int(
            _pick(stored, "audit_retention_days", fallback.audit_retention_days)
        ),
        level=str(_pick(stored, "level", fallback.level)).upper(),
    )


def current_llm_config() -> LlmConfig:
    """Действующая настройка модели там, где сессии базы под рукой нет.

    Собственная короткая сессия, а не сессия запроса: провайдер собирается
    и в фоновой задаче оценки, и в служебных скриптах. Если база недоступна
    или схема ещё не накачена, комплекс не должен падать — он продолжает
    работать на переменных окружения.
    """
    try:
        with SessionLocal() as db:
            return llm_config(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Настройки модели не прочитаны из базы (%s), взяты переменные окружения", exc
        )
        return env_llm_config()


def save_llm(
    db: Session,
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    disable_thinking: bool,
    actor: User | None = None,
) -> tuple[LlmConfig, bool]:
    """Сохраняет настройку модели. Возвращает её и признак смены ключа.

    Пустой ключ означает «не менять», а не «стереть»: администратор,
    поправивший адрес, иначе стирал бы ключ, сам того не заметив. Для
    стирания есть отдельное действие — `clear_llm_key`.
    """
    stored = stored_value(db, LLM_KEY)
    value: dict = {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "disable_thinking": disable_thinking,
    }
    key = api_key.strip()
    key_changed = bool(key) and key != stored.get("api_key")
    if key:
        value["api_key"] = key
    elif "api_key" in stored:
        value["api_key"] = stored["api_key"]

    _write(db, LLM_KEY, value, actor)
    return llm_config(db), key_changed


def clear_llm_key(db: Session, *, actor: User | None = None) -> LlmConfig:
    """Явное стирание ключа доступа.

    Пустая строка записывается в базу намеренно, а не удаляется вместе
    с полем: значение из базы главнее окружения, и удаление поля вернуло бы
    ключ из `.env`, который администратор как раз и хотел отключить.
    """
    value = stored_value(db, LLM_KEY) or _as_stored(llm_config(db))
    value["api_key"] = ""
    _write(db, LLM_KEY, value, actor)
    return llm_config(db)


def save_logging(
    db: Session,
    *,
    audit_retention_days: int,
    level: str,
    actor: User | None = None,
) -> LoggingConfig:
    """Сохраняет параметры журналирования и сразу применяет подробность.

    Проверка нижней границы хранения — в `validate_retention`: её надо
    выполнить до записи и объяснить администратору причину отказа.
    """
    _write(
        db,
        LOGGING_KEY,
        {"audit_retention_days": audit_retention_days, "level": level.upper()},
        actor,
    )
    config = logging_config(db)
    apply_log_level(config.level)
    return config


def retention_error(days: int) -> str | None:
    """Причина, по которой глубину хранения принять нельзя, либо None."""
    if days < MIN_AUDIT_RETENTION_DAYS:
        return (
            f"Глубина хранения журнала аудита не может быть меньше "
            f"{MIN_AUDIT_RETENTION_DAYS} суток: техническое задание требует "
            "хранить журнал безопасности не менее шести месяцев."
        )
    if days > MAX_AUDIT_RETENTION_DAYS:
        return (
            f"Глубина хранения задаётся не более чем на "
            f"{MAX_AUDIT_RETENTION_DAYS} суток."
        )
    return None


def apply_log_level(level: str) -> None:
    """Меняет подробность журнала приложения без перезапуска.

    Уровень ставится корневому журналу: именно от него наследуются
    журналы модулей приложения, заведённые через `logging.getLogger(__name__)`.
    """
    logging.getLogger().setLevel(level.upper())


def _as_stored(config: LlmConfig) -> dict:
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "disable_thinking": config.disable_thinking,
    }


def _write(db: Session, key: str, value: dict, actor: User | None) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        row = SystemSetting(key=key, value=value)
        db.add(row)
    else:
        # Присваивание целиком, а не правка словаря на месте: SQLAlchemy
        # не отслеживает изменения внутри JSON-значения и не сохранил бы их.
        row.value = value
    row.updated_by = actor
    db.flush()
    # Время правки проставляет сама база, и без перечитывания ответ на
    # сохранение вернул бы пустую отметку «кто и когда менял».
    db.refresh(row)
