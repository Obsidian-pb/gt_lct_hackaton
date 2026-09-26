from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import ApplicantStatus, ScenarioStatus, TrainingRole

T = TypeVar("T", ScenarioStatus, ApplicantStatus, TrainingRole)


class ReferenceRepository:
    """Доступ к данным справочников reference (обобщённый CRUD)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self, model: type[T]) -> list[T]:
        order_by: list = [model.name]
        if hasattr(model, "sort_order"):
            order_by = [model.sort_order, model.name]
        result = await self._session.execute(select(model).order_by(*order_by))
        return list(result.scalars().all())

    async def get(self, model: type[T], obj_id: UUID) -> T | None:
        return await self._session.get(model, obj_id)

    async def get_by_code(self, model: type[T], code: str) -> T | None:
        result = await self._session.execute(select(model).where(model.code == code))
        return result.scalar_one_or_none()

    def add(self, obj: T) -> None:
        self._session.add(obj)

    async def delete(self, obj: T) -> None:
        await self._session.delete(obj)