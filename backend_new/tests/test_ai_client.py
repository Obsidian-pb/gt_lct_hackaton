"""Тесты HTTP-клиента ИИ-микросервиса (без сети — MockTransport).

Ядро вынесено в ai_service (см. plans/plan3_ai_microservice.md): здесь
проверяется маппинг маршрутов и ошибок клиента AIServiceClient.
"""
from __future__ import annotations

import pytest
import httpx

from app.services.ai.client import AIConfigError, AIServiceClient, AIServiceUnavailable


def make_client(handler) -> AIServiceClient:
    return AIServiceClient(base_url="http://ai.test", token="token-1",
                           transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_status_success() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/ai/checks"
        assert request.headers["Authorization"] == "Bearer token-1"
        return httpx.Response(200, json={"state": "available", "message": "ok"}, request=request)

    result = await make_client(handler).status()
    assert result["state"] == "available"


@pytest.mark.asyncio
async def test_generate_card_path_and_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/cards/generations"
        body = request.read()
        assert b'"topic"' in body
        return httpx.Response(200, json={"content": {"title": "Пожар"}}, request=request)

    result = await make_client(handler).generate_card({"topic": "пожар на балконе"})
    assert result["content"]["title"] == "Пожар"


@pytest.mark.asyncio
async def test_error_422_raises_value_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "Неверная структура карточки."}, request=request)

    with pytest.raises(ValueError, match="Неверная структура"):
        await make_client(handler).validate_fields({"bad": True})


@pytest.mark.asyncio
async def test_error_503_raises_config() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "AI_SERVICE_TOKEN не настроен"}, request=request)

    with pytest.raises(AIConfigError):
        await make_client(handler).status()


@pytest.mark.asyncio
async def test_error_401_raises_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Неверный токен"}, request=request)

    with pytest.raises(AIServiceUnavailable, match="401"):
        await make_client(handler).status()


@pytest.mark.asyncio
async def test_error_provider_502_raises_runtime() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "ИИ-сервис вернул ошибку HTTP 500."}, request=request)

    with pytest.raises(RuntimeError):
        await make_client(handler).generate_card({"topic": "x"})


@pytest.mark.asyncio
async def test_missing_config_raises_before_request() -> None:
    client = AIServiceClient(base_url="", token="")
    with pytest.raises(AIServiceUnavailable, match="не настроен"):
        await client.status()


@pytest.mark.asyncio
async def test_network_error_raises_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(AIServiceUnavailable, match="недоступен"):
        await make_client(handler).status()