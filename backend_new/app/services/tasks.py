from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import EventClass
from app.models.content import StudyTask, TaskEtalon, TaskExtraFieldSchema
from app.repositories.content import ContentRepository
from app.schemas.tasks import (
    ExtraFieldSchemaIn,
    StudyTaskApproveRequest,
    StudyTaskCreate,
    StudyTaskUpdate,
)


class StudyTaskService:
    """Бизнес-логика учебных задач (окно 8 ТЗ)."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = ContentRepository(session)
        self._session = session

    async def create_task(self, payload: StudyTaskCreate, actor_id: UUID) -> StudyTask:
        if payload.event_class_id is not None:
            event_class = await self._session.get(EventClass, payload.event_class_id)
            if event_class is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Указанная группа происшествий не найдена",
                )
        services = (
            await self._repo.get_services(payload.service_ids)
            if payload.service_ids
            else []
        )
        if len(services) != len(payload.service_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Одна из указанных служб не найдена",
            )

        data = payload.model_dump(
            exclude={
                "service_ids",
                "etalon_content",
                "field_schema",
                "extra_field_schemas",
            }
        )
        task = StudyTask(**data, created_by=actor_id, status="draft")
        task.services = services
        if payload.etalon_content:
            task.etalon = TaskEtalon(
                content=payload.etalon_content, field_schema=payload.field_schema
            )
        task.extra_field_schemas = [
            TaskExtraFieldSchema(**schema.model_dump())
            for schema in payload.extra_field_schemas
        ]
        self._repo.add(task)
        await self._session.commit()
        return await self._require_task(task.id)

    async def update_task(
        self, task_id: UUID, payload: StudyTaskUpdate
    ) -> StudyTask:
        task = await self._require_task(task_id)
        changes = payload.model_dump(exclude_unset=True)
        service_ids = changes.pop("service_ids", None)
        etalon_content = changes.pop("etalon_content", None)
        field_schema = changes.pop("field_schema", None)
        extra_field_schemas = changes.pop("extra_field_schemas", None)
        for field, value in changes.items():
            setattr(task, field, value)
        if service_ids is not None:
            services = await self._repo.get_services(service_ids)
            if len(services) != len(service_ids):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Одна из указанных служб не найдена",
                )
            task.services = services
        if etalon_content is not None or field_schema is not None:
            if task.etalon is None:
                task.etalon = TaskEtalon(
                    content=etalon_content or {},
                    field_schema=field_schema or [],
                )
            else:
                if etalon_content is not None:
                    task.etalon.content = etalon_content
                if field_schema is not None:
                    task.etalon.field_schema = field_schema
        if extra_field_schemas is not None:
            task.extra_field_schemas = [
                TaskExtraFieldSchema(**schema.model_dump())
                for schema in extra_field_schemas
            ]
        await self._session.commit()
        return await self._require_task(task_id)

    async def decide_task(
        self, task_id: UUID, payload: StudyTaskApproveRequest, actor_id: UUID
    ) -> StudyTask:
        """Утверждение/отклонение задачи преподавателем (ТЗ 8: «Утверждена»)."""
        task = await self._require_task(task_id)
        task.status = "approved" if payload.approve else "rejected"
        task.approved_by = actor_id
        task.approved_at = datetime.now(timezone.utc)
        await self._session.commit()
        return await self._require_task(task_id)

    async def delete_task(self, task_id: UUID) -> None:
        task = await self._require_task(task_id)
        now = datetime.now(timezone.utc)
        task.deleted_at = now
        task.purge_after = now + timedelta(days=180)
        await self._session.commit()

    async def _require_task(self, task_id: UUID) -> StudyTask:
        task = await self._repo.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Учебная задача не найдена"
            )
        return task