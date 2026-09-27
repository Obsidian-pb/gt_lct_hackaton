from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.schemas.ai import (
    AIEvalIn,
    AIGenerateIn,
    AIStatusOut,
    CallerReplyIn,
    CallerReplyOut,
    ReferencePreviewIn,
    ReferencePreviewOut,
    ServiceReplyIn,
    ServiceReplyOut,
    ValidateFieldsIn,
    ValidateFieldsOut,
)
from app.schemas.cards import CardOut
from app.schemas.tasks import StudyTaskOut, task_to_out
from app.services.ai.service import AIService

router = APIRouter(tags=["ai"])
editor_access = require_roles("system_admin", "admin", "teacher")
teacher_access = require_roles("system_admin", "admin", "teacher")


@router.get("/system/ai/status", response_model=AIStatusOut, summary="Проверка доступности ИИ (мониторинг)")
async def ai_status(
    _: Annotated[object, Depends(editor_access)],
) -> AIStatusOut:
    return AIStatusOut(**await AIService.status())


@router.post(
    "/study-tasks/{task_id}/generate",
    response_model=StudyTaskOut,
    summary="Генерация содержимого учебной задачи ИИ",
)
async def generate_task(
    task_id: UUID,
    payload: AIGenerateIn | None,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> StudyTaskOut:
    task = await AIService(session).generate_task(task_id, payload.model_dump() if payload else {})
    return task_to_out(task)


@router.post(
    "/study-tasks/{task_id}/reference-preview",
    response_model=ReferencePreviewOut,
    summary="Превью эталонного ответа ИИ (запись в эталон задачи)",
)
async def reference_preview(
    task_id: UUID,
    payload: ReferencePreviewIn | None,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> ReferencePreviewOut:
    task, reference = await AIService(session).reference_preview(
        task_id, payload.model_dump() if payload else {}
    )
    return ReferencePreviewOut(
        task_id=task.id,
        etalon_content=task.etalon.content if task.etalon else {},
        field_schema=task.etalon.field_schema if task.etalon else [],
        reference=reference,
    )


@router.post(
    "/study-tasks/{task_id}/caller-reply",
    response_model=CallerReplyOut,
    summary="Реплика заявителя (мастерская преподавателя)",
)
async def task_caller_reply(
    task_id: UUID,
    payload: CallerReplyIn,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> CallerReplyOut:
    result = await AIService(session).caller_reply_for_task(task_id, payload.model_dump())
    return CallerReplyOut(**result)


@router.post(
    "/study-tasks/{task_id}/validate-fields",
    response_model=ValidateFieldsOut,
    summary="Валидация полей карточки (ИИ-формат мастерской)",
)
async def validate_fields(
    task_id: UUID,
    payload: ValidateFieldsIn,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> ValidateFieldsOut:
    return ValidateFieldsOut(**await AIService(session).validate_fields(task_id, payload.content))


@router.post(
    "/cards/{card_id}/caller-reply",
    response_model=CallerReplyOut,
    summary="Реплика заявителя (симулятор обучающегося)",
)
async def card_caller_reply(
    card_id: UUID,
    payload: CallerReplyIn,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CallerReplyOut:
    result = await AIService(session).caller_reply_for_card(card_id, payload.model_dump(), current_user)
    return CallerReplyOut(**result)


@router.post(
    "/cards/{card_id}/service-reply",
    response_model=ServiceReplyOut,
    summary="Реплика службы ДДС (исходящий звонок с учебными помехами)",
)
async def card_service_reply(
    card_id: UUID,
    payload: ServiceReplyIn,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ServiceReplyOut:
    result = await AIService(session).service_reply_for_card(card_id, payload.model_dump(), current_user)
    return ServiceReplyOut(**result)


@router.post(
    "/cards/{card_id}/ai-eval",
    response_model=CardOut,
    summary="Предварительная оценка ИИ (запись в ai_score / ai_eval_details)",
)
async def card_ai_eval(
    card_id: UUID,
    payload: AIEvalIn | None,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> CardOut:
    card, _assessment = await AIService(session).assess_card(
        card_id, payload.model_dump() if payload else {}
    )
    return CardOut.model_validate(card)
