"""Сборка провайдера ИИ-оценки по действующей настройке комплекса.

Провайдер кешируется: HTTP-клиент с пулом соединений незачем создавать
на каждую проверку комментария. Но настройку администратор меняет из
интерфейса, и смена обязана действовать без перезапуска, поэтому кеш
привязан не к процессу, как было с `lru_cache`, а к отпечатку настройки.
Отпечаток сверяется при каждом обращении: рабочих процессов у приложения
несколько, а правку настройки делает только один из них — остальные
узнают о ней именно так.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.llm.base import CommentReview, GeneratedScenario, LLMProvider
from app.llm.gigachat import GigaChatProvider
from app.llm.openai_compatible import OpenAICompatibleProvider, _is_local
from app.llm.stub import StubProvider
from app.services.system_settings import LlmConfig, current_llm_config

logger = logging.getLogger(__name__)

# Отсрочка закрытия HTTP-клиента прежнего провайдера. Клиент закрывать надо —
# иначе каждая правка настроек оставляла бы в процессе живой пул соединений.
# Но закрытие посреди запроса оборвало бы уже идущую проверку комментария
# ошибкой, которой обработчик оценки не ждёт, поэтому старый клиент доживает
# запас поверх таймаута обращения к модели и закрывается уже пустым.
CLOSE_DELAY_SECONDS = 90.0

_provider: LLMProvider | None = None
_fingerprint: tuple | None = None
# Ссылки на отложенные закрытия: без них сборщик мусора вправе убрать задачу
# вместе с незакрытым клиентом.
_closing: set[asyncio.Task] = set()


@dataclass(frozen=True)
class ProbeResult:
    """Итог проверки связи с моделью."""

    ok: bool
    detail: str
    elapsed_ms: int


def build_llm_provider(config: LlmConfig) -> LLMProvider:
    """Создаёт провайдера по настройке, минуя кеш.

    Отдельно от `get_llm_provider` — нужен для проверки связи на ещё
    не сохранённой настройке.
    """
    settings = get_settings()
    if config.provider == "stub":
        return StubProvider()
    if config.provider == "gigachat":
        # Корневой сертификат НУЦ Минцифры и область доступа остаются
        # в переменных окружения: их задают один раз при развёртывании,
        # а из интерфейса меняют адрес, модель и ключ.
        verify: bool | str = settings.gigachat_ca_bundle or settings.gigachat_verify_tls
        return GigaChatProvider(
            auth_key=config.api_key,
            scope=settings.gigachat_scope,
            model=config.model,
            timeout=config.timeout_seconds,
            verify=verify,
        )
    return OpenAICompatibleProvider(
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        timeout=config.timeout_seconds,
        name=config.provider,
        disable_thinking=config.disable_thinking,
    )


def is_external(config: LlmConfig) -> bool:
    """Уходят ли тексты обучающихся за пределы учебного комплекса.

    Признак считается по адресу, а не по названию провайдера: «local» —
    это всего лишь имя, а модель по такому профилю может стоять и в другой
    сети. Для изолированного контура вопрос существенный, поэтому ответ
    на него показывается администратору прямо в настройке.
    """
    if config.provider == "stub":
        return False
    if config.provider == "gigachat":
        return True
    return not _is_local(config.base_url)


def get_llm_provider() -> LLMProvider:
    global _provider, _fingerprint

    config = current_llm_config()
    fingerprint = config.fingerprint()
    if _provider is None or _fingerprint != fingerprint:
        previous, _provider, _fingerprint = _provider, build_llm_provider(config), fingerprint
        _close_later(previous)
    return _provider


def reset_llm_provider() -> None:
    """Сбрасывает кеш после правки настроек.

    Сверки отпечатка хватило бы и без этого, но тогда прежний клиент жил бы
    до следующего обращения к модели — а его может не быть до конца занятия.
    """
    global _provider, _fingerprint

    previous, _provider, _fingerprint = _provider, None, None
    _close_later(previous)


async def probe_llm(config: LlmConfig) -> ProbeResult:
    """Проверяет связь с моделью на переданной настройке.

    Провайдер создаётся отдельно от кеша и закрывается сразу: проверка должна
    работать и на ещё не применённой настройке, иначе администратор узнавал бы
    об ошибке в адресе только на занятии — смысловой разбор комментариев
    просто молча перестал бы работать.
    """
    if config.provider == "stub":
        return ProbeResult(
            ok=True,
            detail=(
                "Языковая модель не используется: выбран режим без модели. "
                "Оценка выставляется по детерминированным проверкам."
            ),
            elapsed_ms=0,
        )

    provider = build_llm_provider(config)
    started = time.monotonic()
    try:
        model = await provider.probe()
        elapsed = int((time.monotonic() - started) * 1000)
        return ProbeResult(
            ok=True, detail=f"Модель «{model}» ответила за {elapsed} мс.", elapsed_ms=elapsed
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = int((time.monotonic() - started) * 1000)
        return ProbeResult(ok=False, detail=explain_llm_failure(exc), elapsed_ms=elapsed)
    finally:
        # Временный клиент никто больше не держит, поэтому закрывается сразу,
        # а не по отсрочке: иначе проверки связи копили бы пулы соединений.
        await _aclose(provider)


def explain_llm_failure(exc: BaseException) -> str:
    """Переводит отказ обращения к модели в объяснение для администратора.

    Администратору учебного комплекса недоступны ни журналы контейнеров,
    ни трассировка: «ошибка соединения» не подсказала бы ему, что именно
    поправить — адрес, ключ или имя модели.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return (
                f"Модель отклонила ключ доступа (HTTP {code}). Проверьте ключ "
                "и права учётной записи у поставщика модели."
            )
        if code == 404:
            return (
                f"По указанному адресу нет OpenAI-совместимого API либо не найдена "
                f"модель (HTTP 404). Адрес должен оканчиваться на /v1, а имя модели — "
                f"совпадать с тем, как её называет сервер. {_body(exc.response)}"
            )
        if code == 429:
            return (
                "Поставщик модели ограничил частоту обращений (HTTP 429). "
                "Настройка верна, но обращаться к модели сейчас нельзя."
            )
        return f"Модель ответила ошибкой HTTP {code}. {_body(exc.response)}"
    if isinstance(exc, httpx.TimeoutException):
        return (
            "Модель не ответила за отведённое время. Так бывает, если адрес ведёт "
            "в сеть, где модели нет, или сама модель ещё загружается."
        )
    if isinstance(exc, httpx.ConnectError):
        return (
            "Не удалось подключиться по указанному адресу. Проверьте, что модель "
            "запущена и адрес доступен с сервера комплекса, а не только с вашего "
            "рабочего места."
        )
    if isinstance(exc, httpx.InvalidURL) or isinstance(exc, httpx.UnsupportedProtocol):
        return "Адрес модели указан неверно: нужен полный адрес вида http://узел:порт/v1."
    if isinstance(exc, httpx.HTTPError):
        return f"Обращение к модели не удалось: {exc}"
    return f"Неожиданная ошибка при обращении к модели: {type(exc).__name__}: {exc}"


def _body(response: httpx.Response) -> str:
    """Начало ответа сервера: в нём обычно и сказано, что именно не так."""
    try:
        text = response.text.strip().replace("\n", " ")
    except Exception:  # noqa: BLE001
        return ""
    return f"Ответ сервера: {text[:200]}" if text else ""


async def _aclose(provider: LLMProvider) -> None:
    aclose = getattr(provider, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось закрыть клиент провайдера: %s", exc)


def _close_later(provider: LLMProvider | None) -> None:
    if provider is None or getattr(provider, "aclose", None) is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Вне цикла событий (скрипты, разовые вызовы) отложить закрытие некуда,
        # а закрывать нечем: соединения освободятся с завершением процесса.
        return

    async def close_after_delay() -> None:
        await asyncio.sleep(CLOSE_DELAY_SECONDS)
        await _aclose(provider)

    task = loop.create_task(close_after_delay())
    _closing.add(task)
    task.add_done_callback(_closing.discard)


__all__ = [
    "CommentReview",
    "GeneratedScenario",
    "LLMProvider",
    "ProbeResult",
    "build_llm_provider",
    "explain_llm_failure",
    "get_llm_provider",
    "is_external",
    "probe_llm",
    "reset_llm_provider",
]
