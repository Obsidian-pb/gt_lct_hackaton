from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.repositories.content import ContentRepository
from app.schemas.tasks import (
    StudyTaskApproveRequest,
    StudyTaskCreate,
    StudyTaskOut,
    StudyTaskUpdate,
    task_to_out,
)
from app.services.tasks import StudyTaskService

router = APIRouter(prefix="/study-tasks", tags=["study-tasks"])
editor_access = require_roles("system_admin", "admin", "teacher")


@router.get("", response_model=list[StudyTaskOut], summary="Список учебных задач (окно 7 ТЗ)")
async def list_tasks(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    difficulty: int | None = None,
    status: str | None = None,
    event_class_id: UUID | None = None,
    search: str | None = None,
) -> list[StudyTaskOut]:
    tasks = await ContentRepository(session).list_tasks(
        difficulty=difficulty,
        status=status,
        event_class_id=event_class_id,
        search=search,
    )
    return [task_to_out(t) for t in tasks]


@router.post("", response_model=StudyTaskOut, status_code=201, summary="Создание учебной задачи (окно 8 ТЗ)")
async def create_task(
    payload: StudyTaskCreate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(editor_access)],
) -> StudyTaskOut:
    task = await StudyTaskService(session).create_task(payload, current_user.id)
    return task_to_out(task)


@router.get("/{task_id}", response_model=StudyTaskOut, summary="Учебная задача")
async def get_task(
    task_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StudyTaskOut:
    task = await ContentRepository(session).get_task(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Учебная задача не найдена"
        )
    return task_to_out(task)


@router.patch("/{task_id}", response_model=StudyTaskOut, summary="Изменение учебной задачи")
async def update_task(
    task_id: UUID,
    payload: StudyTaskUpdate,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> StudyTaskOut:
    task = await StudyTaskService(session).update_task(task_id, payload)
    return task_to_out(task)


@router.delete("/{task_id}", status_code=204, summary="Удаление учебной задачи")
async def delete_task(
    task_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> None:
    await StudyTaskService(session).delete_task(task_id)


@router.post("/{task_id}/approve", response_model=StudyTaskOut, summary="Утверждение/отклонение задачи")
async def decide_task(
    task_id: UUID,
    payload: StudyTaskApproveRequest,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> StudyTaskOut:
    task = await StudyTaskService(session).decide_task(task_id, payload, current_user.id)
    return task_to_out(task)


@router.post("/{task_id}/generate", status_code=501, summary="Генерация задачи ИИ (заглушка)")
async def generate_task(
    task_id: UUID,
    _: CurrentUser,
    __: Annotated[object, Depends(editor_access)],
) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Генерация учебных задач ИИ будет реализована после интеграции ИИ-модуля",
    )