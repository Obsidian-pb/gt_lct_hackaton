from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Scenario
from app.models.reference import ScenarioStatus
from app.repositories.content import ContentRepository
from app.schemas.scenarios import ScenarioCreate, ScenarioUpdate


class ScenarioService:
    """Бизнес-логика учебных сценариев (окно 6 ТЗ)."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = ContentRepository(session)
        self._session = session

    async def create_scenario(self, payload: ScenarioCreate, actor_id: UUID) -> Scenario:
        scenario = Scenario(
            topic=payload.topic,
            description=payload.description,
            scenario_status_id=payload.scenario_status_id,
            created_by=actor_id,
        )
        if scenario.scenario_status_id is None:
            draft = await self._session.scalar(
                select(ScenarioStatus).where(ScenarioStatus.code == "draft")
            )
            scenario.scenario_status_id = draft.id if draft else None
        self._repo.add(scenario)
        await self._session.commit()
        return await self._require_scenario(scenario.id)

    async def update_scenario(
        self, scenario_id: UUID, payload: ScenarioUpdate
    ) -> Scenario:
        scenario = await self._require_scenario(scenario_id)
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(scenario, field, value)
        await self._session.commit()
        return await self._require_scenario(scenario_id)

    async def approve_scenario(
        self, scenario_id: UUID, actor_id: UUID, approve: bool = True
    ) -> Scenario:
        scenario = await self._require_scenario(scenario_id)
        code = "approved" if approve else "archived"
        target = await self._session.scalar(
            select(ScenarioStatus).where(ScenarioStatus.code == code)
        )
        scenario.scenario_status_id = target.id if target else scenario.scenario_status_id
        scenario.approved_by = actor_id if approve else None
        scenario.approved_at = datetime.now(timezone.utc) if approve else None
        await self._session.commit()
        return await self._require_scenario(scenario_id)

    async def delete_scenario(self, scenario_id: UUID) -> None:
        scenario = await self._require_scenario(scenario_id)
        if await self._repo.scenario_in_trainings(scenario_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Сценарий используется в тренировках и не может быть удалён",
            )
        now = datetime.now(timezone.utc)
        scenario.deleted_at = now
        scenario.purge_after = now + timedelta(days=180)
        await self._session.commit()

    async def add_task(self, scenario_id: UUID, task_id: UUID) -> Scenario:
        scenario = await self._require_scenario(scenario_id)
        task = await self._repo.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Учебная задача не найдена"
            )
        if task.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="В сценарий можно включать только утверждённые учебные задачи",
            )
        if await self._repo.scenario_has_task(scenario_id, task_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Задача уже включена в сценарий",
            )
        await self._repo.add_scenario_task(scenario_id, task_id)
        await self._session.commit()
        return await self._require_scenario(scenario_id)

    async def remove_task(self, scenario_id: UUID, task_id: UUID) -> Scenario:
        await self._require_scenario(scenario_id)
        await self._repo.remove_scenario_task(scenario_id, task_id)
        await self._session.commit()
        return await self._require_scenario(scenario_id)

    async def _require_scenario(self, scenario_id: UUID) -> Scenario:
        scenario = await self._repo.get_scenario(scenario_id)
        if scenario is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Сценарий не найден"
            )
        return scenario