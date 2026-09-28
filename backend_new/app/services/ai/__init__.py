"""Клиент stateless ИИ-микросервиса (ai_service).

ИИ-ядро вынесено из backend_new в отдельный сервис (см. plans/plan3_ai_microservice.md):
ключ провайдера больше не хранится в этом процессе. Все обращения к ИИ идут
по HTTP с Bearer AI_SERVICE_TOKEN; состояние диалога и карточек остаётся в БД
backend_new.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.ai.client import AIConfigError, AIServiceClient, AIServiceUnavailable

__all__ = [
    "AIConfigError",
    "AIServiceClient",
    "AIServiceUnavailable",
    "get_ai_client",
    "reset_client_cache",
]


@lru_cache
def get_ai_client() -> AIServiceClient:
    """Единственный экземпляр клиента на процесс."""
    settings = get_settings()
    return AIServiceClient(base_url=settings.ai_service_url, token=settings.ai_service_token)


def reset_client_cache() -> None:
    """Сброс кэша после изменения настроек (например, в тестах)."""
    get_ai_client.cache_clear()
