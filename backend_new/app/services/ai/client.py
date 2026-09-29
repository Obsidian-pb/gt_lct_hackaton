"""HTTP-клиент к stateless ИИ-микросервису (ai_service).

Заменяет прямое обращение к ядру (см. plans/plan3_ai_microservice.md): ключ
ИИ-провайдера больше не хранится в backend_new — интеграция идёт по HTTP
с Bearer AI_SERVICE_TOKEN. Состояние диалога и карточек остаётся в БД
backend_new; микросервис получает снимки в теле запроса.

Маппинг ошибок:
- AIConfigError (503) — сервис не настроен/недоступен/отклонил токен;
- ValueError (422) — микросервис отклонил входные данные;
- RuntimeError (502) — ошибка внешнего ИИ-провайдера.
"""
from __future__ import annotations

from typing import Any

import httpx


class AIConfigError(RuntimeError):
    """ИИ-микросервис не настроен или недоступен."""


class AIServiceUnavailable(AIConfigError):
    """Частный случай AIConfigError: сеть/токен/настройка сервиса."""


class AIServiceClient:
    """Асинхронный клиент stateless REST-операций микросервиса."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 75.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = (base_url or "").rstrip("/")
        self._token = token or ""
        self._timeout = timeout
        self._transport = transport

    # --- низкоуровневый вызов -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _handle(self, resp: httpx.Response) -> Any:
        try:
            data = resp.json()
        except ValueError:
            data = None
        if resp.is_success:
            return data
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("detail") or "")
        if resp.status_code == 422:
            raise ValueError(detail or "ИИ-сервис отклонил запрос (422).")
        if resp.status_code == 401:
            raise AIServiceUnavailable("ИИ-сервис отклонил токен доступа (401): проверьте AI_SERVICE_TOKEN.")
        if resp.status_code == 503:
            raise AIConfigError(detail or "ИИ-сервис не настроен (503): задайте ключ провайдера и токен.")
        raise RuntimeError(detail or f"ИИ-сервис вернул ошибку HTTP {resp.status_code}.")

    async def _post(self, path: str, payload: dict | None = None) -> Any:
        if not self._base or not self._token:
            raise AIServiceUnavailable("ИИ-сервис не настроен: задайте AI_SERVICE_URL и AI_SERVICE_TOKEN в .env backend_new.")
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                resp = await client.post(self._base + path, json=payload or {}, headers=self._headers())
        except httpx.HTTPError as exc:
            raise AIServiceUnavailable(f"ИИ-сервис недоступен ({exc.__class__.__name__}). Запустите ai_service.") from None
        return self._handle(resp)

    # --- stateless-операции ---------------------------------------------------

    async def status(self) -> dict:
        """Проверка доступности ИИ (без генерации)."""
        return await self._post("/api/v1/ai/checks")

    async def generate_card(self, request: dict) -> dict:
        """Генерация содержимого карточки: {topic, location, flags, index, total, incident_class}."""
        return await self._post("/api/v1/cards/generations", request)

    async def reference_preview(self, request: dict) -> dict:
        """Превью эталона: {content, caller_scenario, incident_class}."""
        return await self._post("/api/v1/cards/reference-previews", request)

    async def caller_reply(self, request: dict) -> dict:
        """Реплика заявителя: {content, caller_scenario, question, turns, level}."""
        return await self._post("/api/v1/cards/caller-replies", request)

    async def service_reply(self, request: dict) -> dict:
        """Реплика службы ДДС: {service, persona, level, history, question, mode, attempt}."""
        return await self._post("/api/v1/cards/service-replies", request)

    async def validate_fields(self, content: dict) -> dict:
        """Локальная валидация содержимого карточки."""
        return await self._post("/api/v1/cards/validations", {"content": content})

    async def assess(self, request: dict) -> dict:
        """Предварительная оценка: {labels, card, expected, history, hints_used}."""
        return await self._post("/api/v1/assessments", request)