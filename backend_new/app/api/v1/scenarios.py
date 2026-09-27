from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.repositories.content import ContentRepository
from app.schemas.scenarios import (
    ScenarioCreate,
    ScenarioDetailOut,
    ScenarioOut,
    ScenarioUpdate,
    TaskLinkIn,
)
from app.schemas.tasks import task_to_out
from app.services.scenarios import ScenarioService

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
editor_access = require_roles("system_admin", "admin", "teacher")


def scenario_to_out(scenario, task_count: int | None = None) -> ScenarioOut:
    data = ScenarioOut.model_validate(scenario).model_dump()
    data["task_count"] = task_count if task_count is not None else len(scenario.tasks)
    return ScenarioOut(**data)


@router.get("", response_model=list[ScenarioOut], summary="Список учебных сценариев (окно 5 ТЗ)")
async def list_scenarios(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ScenarioOut]:
    repo = ContentRepository(session)
    scenarios = await repo.list_scenarios()
    result = []
    for scenario in scenarios:
        count = await repo.count_scenario_tasks(scenario.id)
        result.append(scenario_to_out(scenario, count))
    return result


@router.post("", response_model=ScenarioDetailOut, status_code=201, summary="Создание сценария (окно 6 ТЗ)")
async def create_scenario(
    payload: ScenarioCreate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(editor_access)],
) -> ScenarioDetailOut:
    scenario = await ScenarioService(session).create_scenario(payload, current_user.id)
    return ScenarioDetailOut(
        **scenario_to_out(scenario, 0).model_dump(), tasks=[]
    )


@router.get("/{scenario_id}", response_model=ScenarioDetailOut, summary="Сценарий с задачами")
async def get_scenario(
    scenario_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScenarioDetailOut:
    scenario = await ContentRepository(session).get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Сценарий не найден"
        )
    return ScenarioDetailOut(
        **scenario_to_out(scenario, len(scenario.tasks)).model_dump(),
        tasks=[task_to_out(t) for t in scenario.tasks],
    )


@router.patch("/{scenario_id}", response_model=ScenarioDetailOut, summary="Изменение сценария")
async def update_scenario(
    scenario_id: UUID,
    payload: ScenarioUpdate,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> ScenarioDetailOut:
    scenario = await ScenarioService(session).update_scenario(scenario_id, payload)
    return ScenarioDetailOut(
        **scenario_to_out(scenario, len(scenario.tasks)).model_dump(),
        tasks=[task_to_out(t) for t in scenario.tasks],
    )


@router.delete("/{scenario_id}", status_code=204, summary="Удаление сценария")
async def delete_scenario(
    scenario_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> None:
    await ScenarioService(session).delete_scenario(scenario_id)


@router.post("/{scenario_id}/approve", response_model=ScenarioDetailOut, summary="Утверждение сценария")
async def approve_scenario(
    scenario_id: UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> ScenarioDetailOut:
    scenario = await ScenarioService(session).approve_scenario(
        scenario_id, current_user.id
    )
    return ScenarioDetailOut(
        **scenario_to_out(scenario, len(scenario.tasks)).model_dump(),
        tasks=[task_to_out(t) for t in scenario.tasks],
    )


@router.post("/{scenario_id}/tasks", response_model=ScenarioDetailOut, summary="Добавление задачи в сценарий")
async def add_task_to_scenario(
    scenario_id: UUID,
    payload: TaskLinkIn,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> ScenarioDetailOut:
    scenario = await ScenarioService(session).add_task(scenario_id, payload.study_task_id)
    return ScenarioDetailOut(
        **scenario_to_out(scenario, len(scenario.tasks)).model_dump(),
        tasks=[task_to_out(t) for t in scenario.tasks],
    )


@router.delete("/{scenario_id}/tasks/{task_id}", response_model=ScenarioDetailOut, summary="Удаление задачи из сценария")
async def remove_task_from_scenario(
    scenario_id: UUID,
    task_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> ScenarioDetailOut:
    scenario = await ScenarioService(session).remove_task(scenario_id, task_id)
    return ScenarioDetailOut(
        **scenario_to_out(scenario, len(scenario.tasks)).model_dump(),
        tasks=[task_to_out(t) for t in scenario.tasks],
    )