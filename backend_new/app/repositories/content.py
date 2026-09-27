from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Service
from app.models.content import (
    Scenario,
    StudyMaterial,
    StudyTask,
    TaskEtalon,
    scenario_tasks,
)
from app.models.training import training_scenarios


class ContentRepository:
    """Доступ к данным учебного контента (задачи, сценарии, материалы)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Учебные задачи ---
    async def list_tasks(
        self,
        *,
        difficulty: int | None = None,
        status: str | None = None,
        event_class_id: UUID | None = None,
        search: str | None = None,
    ) -> list[StudyTask]:
        query = (
            select(StudyTask)
            .options(selectinload(StudyTask.services), selectinload(StudyTask.etalon))
            .where(StudyTask.deleted_at.is_(None))
            .order_by(StudyTask.created_at.desc())
        )
        if difficulty is not None:
            query = query.where(StudyTask.difficulty == difficulty)
        if status is not None:
            query = query.where(StudyTask.status == status)
        if event_class_id is not None:
            query = query.where(StudyTask.event_class_id == event_class_id)
        if search:
            query = query.where(StudyTask.caller_message.ilike(f"%{search}%"))
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_task(self, task_id: UUID) -> StudyTask | None:
        result = await self._session.execute(
            select(StudyTask)
            .options(selectinload(StudyTask.services), selectinload(StudyTask.etalon))
            .where(StudyTask.id == task_id, StudyTask.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    def add(self, obj) -> None:
        self._session.add(obj)

    async def get_services(self, service_ids: list[UUID]) -> list[Service]:
        result = await self._session.execute(
            select(Service).where(Service.id.in_(service_ids))
        )
        return list(result.scalars().all())

    # --- Сценарии ---
    async def list_scenarios(self) -> list[Scenario]:
        result = await self._session.execute(
            select(Scenario)
            .where(Scenario.deleted_at.is_(None))
            .order_by(Scenario.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_scenario(self, scenario_id: UUID) -> Scenario | None:
        result = await self._session.execute(
            select(Scenario)
            .options(selectinload(Scenario.tasks))
            .where(Scenario.id == scenario_id, Scenario.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def count_scenario_tasks(self, scenario_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(scenario_tasks)
            .where(scenario_tasks.c.scenario_id == scenario_id)
        )
        return int(result.scalar_one())

    async def scenario_has_task(self, scenario_id: UUID, task_id: UUID) -> bool:
        result = await self._session.execute(
            select(scenario_tasks.c.scenario_id).where(
                scenario_tasks.c.scenario_id == scenario_id,
                scenario_tasks.c.study_task_id == task_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_scenario_task(self, scenario_id: UUID, task_id: UUID) -> None:
        await self._session.execute(
            scenario_tasks.insert().values(
                scenario_id=scenario_id, study_task_id=task_id
            )
        )

    async def remove_scenario_task(self, scenario_id: UUID, task_id: UUID) -> None:
        await self._session.execute(
            scenario_tasks.delete().where(
                scenario_tasks.c.scenario_id == scenario_id,
                scenario_tasks.c.study_task_id == task_id,
            )
        )

    # --- Методические материалы ---
    async def list_materials(self) -> list[StudyMaterial]:
        result = await self._session.execute(
            select(StudyMaterial)
            .where(StudyMaterial.deleted_at.is_(None))
            .order_by(StudyMaterial.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_material(self, material_id: UUID) -> StudyMaterial | None:
        return await self._session.get(StudyMaterial, material_id)

    async def scenario_in_trainings(self, scenario_id: UUID) -> bool:
        result = await self._session.execute(
            select(training_scenarios.c.id).where(
                training_scenarios.c.scenario_id == scenario_id
            )
        )
        return result.first() is not None