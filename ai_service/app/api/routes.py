"""Stateless REST-маршруты ИИ-микросервиса.

Каждая операция повторяет сигнатуру функции ядра; состояние (история диалога,
карточки) передаёт вызывающая сторона — backend_new. Ошибки:
- 422 — невалидные входные данные (ValueError);
- 503 — не настроен провайдер/ключ (AIConfigError);
- 502 — ошибка внешнего ИИ-провайдера.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.schemas.ai import (
    AIStatusOut,
    AssessIn,
    CallerReplyIn,
    CardGenerationIn,
    HealthOut,
    ReferencePreviewIn,
    ServiceReplyIn,
    ValidateFieldsIn,
)
from app.services.ai import AIConfigError, ai_core, card_caller, card_factory, card_reference, dds, get_provider

router = APIRouter(tags=["ai"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, AIConfigError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/health", response_model=HealthOut, summary="Живучесть сервиса без вызова ИИ")
async def health() -> HealthOut:
    settings = get_settings()
    return HealthOut(status="ok", service=settings.app_name, version=settings.app_version)


@router.get("/metadata", summary="Общие справочники: группы, каталог, поля карточки")
async def metadata() -> dict[str, Any]:
    return card_factory.metadata()


@router.post("/ai/checks", response_model=AIStatusOut, summary="Проверка доступности ИИ без генерации")
async def ai_checks() -> AIStatusOut:
    try:
        return AIStatusOut(**get_provider().status())
    except Exception as exc:  # noqa: BLE001 - единый маппинг ошибок ядра
        raise _error(exc) from None


@router.post("/cards/generations", summary="Генерация содержимого карточки (одна позиция)")
async def cards_generations(payload: CardGenerationIn) -> dict[str, Any]:
    try:
        return card_factory.generate(get_provider(), payload.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from None


@router.post("/cards/reference-previews", summary="Превью эталонного ответа")
async def cards_reference_previews(payload: ReferencePreviewIn) -> dict[str, Any]:
    try:
        return card_reference.generate(get_provider(), payload.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from None


@router.post("/cards/caller-replies", summary="Реплика заявителя (предпросмотр/симулятор)")
async def cards_caller_replies(payload: CallerReplyIn) -> dict[str, Any]:
    try:
        return card_caller.ask(get_provider(), payload.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from None


@router.post("/cards/service-replies", summary="Реплика службы ДДС с помехами канала")
async def cards_service_replies(payload: ServiceReplyIn) -> dict[str, Any]:
    try:
        reply, delivered = dds.service_reply(get_provider(), **payload.model_dump(exclude_none=True))
        return {"reply": reply, "delivered": delivered}
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from None


@router.post("/cards/validations", summary="Локальная валидация содержимого карточки")
async def cards_validations(payload: ValidateFieldsIn) -> dict[str, Any]:
    try:
        return {"valid": True, "content": card_factory.validate_content(payload.content)}
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from None


@router.post("/assessments", summary="Предварительная оценка ИИ по эталону и разговору")
async def assessments(payload: AssessIn) -> dict[str, Any]:
    try:
        return ai_core.assess_card(get_provider(), **payload.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from None