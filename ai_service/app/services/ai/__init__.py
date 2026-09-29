"""ИИ-ядро тренажёра: адаптеры провайдеров и генерация учебных карточек.

Вынесено из backend_new в отдельный stateless-микросервис (см. plan3).
Ключ провайдера живёт только в настройках этого сервиса (.env /
config.local.json) и не отдаётся ни браузеру, ни backend_new: интеграция
выполняется через REST API микросервиса с Bearer-токеном.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.ai.provider import AIProvider, ProviderHTTPError

__all__ = [
    "AIProvider",
    "ProviderHTTPError",
    "AIConfigError",
    "get_provider",
    "reset_provider_cache",
    "provider_overrides",
]


class AIConfigError(RuntimeError):
    """Неверная конфигурация ИИ-провайдера (ключ, провайдер, адрес, модель)."""


def provider_overrides() -> dict:
    """Настройки ИИ из .env -> приоритетные значения для AIProvider."""
    settings = get_settings()
    overrides: dict = {}
    if settings.ai_provider:
        overrides["provider"] = settings.ai_provider
    if settings.ai_base_url:
        overrides["base_url"] = settings.ai_base_url
    if settings.ai_model:
        overrides["model"] = settings.ai_model
    if settings.ai_api_key:
        overrides["authorization_key"] = settings.ai_api_key
    if settings.ai_scope and settings.ai_scope != "auto":
        overrides["scope"] = settings.ai_scope
    if settings.ai_oauth_url:
        overrides["oauth_url"] = settings.ai_oauth_url
    if settings.ai_ca_bundle:
        overrides["ca_bundle"] = settings.ai_ca_bundle
    if not settings.ai_verify_ssl:
        overrides["verify_ssl"] = False
    return overrides


@lru_cache
def get_provider() -> AIProvider:
    """Единственный экземпляр провайдера на процесс (кэш токена GigaChat)."""
    try:
        return AIProvider(provider_overrides())
    except ValueError as exc:
        raise AIConfigError(str(exc)) from None


def reset_provider_cache() -> None:
    """Сброс кэша после изменения настроек (например, в тестах)."""
    get_provider.cache_clear()