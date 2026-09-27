from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference import ApplicantStatus, ScenarioStatus, TrainingRole
from app.repositories.reference import ReferenceRepository

T = TypeVar("T", ScenarioStatus, ApplicantStatus, TrainingRole)


class ReferenceService:
    """Бизнес-логика управления справочниками reference (обобщённый CRUD)."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = ReferenceRepository(session)
        self._session = session

    async def list(self, model: type[T]) -> list[T]:
        return await self._repo.list_all(model)

    async def create(self, model: type[T], payload: BaseModel) -> T:
        existing = await self._repo.get_by_code(model, payload.code)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Запись с кодом '{payload.code}' уже существует",
            )
        obj = model(**payload.model_dump())
        self._repo.add(obj)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Запись уже существует"
            )
        return obj

    async def update(self, model: type[T], obj_id: UUID, payload: BaseModel) -> T:
        obj = await self._repo.get(model, obj_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Запись не найдена"
            )
        changes = payload.model_dump(exclude_unset=True)
        code = changes.get("code")
        if code is not None:
            existing = await self._repo.get_by_code(model, code)
            if existing is not None and existing.id != obj.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Код '{code}' уже используется",
                )
        for field, value in changes.items():
            setattr(obj, field, value)
        await self._session.commit()
        return obj

    async def delete(self, model: type[T], obj_id: UUID) -> None:
        obj = await self._repo.get(model, obj_id)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Запись не найдена"
            )
        await self._repo.delete(obj)
        await self._session.commit()