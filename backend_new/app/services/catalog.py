from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import (
    EventClass,
    EventClassExtraField,
    EventFeature1,
    EventFeature2,
    EventFeature3,
    EventType,
    Service,
)
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    EventClassCreate,
    EventClassUpdate,
    ServiceCreate,
    ServiceUpdate,
)


def compute_event_number(event_type_code: int, f1: int, f2: int, f3: int) -> int:
    """Номер события: Г × 1 000 000 + Признак1 × 10 000 + Признак2 × 100 + Признак3."""
    return event_type_code * 1_000_000 + f1 * 10_000 + f2 * 100 + f3


class CatalogService:
    """Бизнес-логика служб и классификатора происшествий."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = CatalogRepository(session)
        self._session = session

    # --- Службы ---
    async def create_service(self, payload: ServiceCreate) -> Service:
        if await self._repo.get_service_by_code(payload.code) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Служба с кодом '{payload.code}' уже существует",
            )
        service = Service(**payload.model_dump())
        self._repo.add(service)
        await self._session.commit()
        return service

    async def update_service(self, service_id: UUID, payload: ServiceUpdate) -> Service:
        service = await self._require_service(service_id)
        changes = payload.model_dump(exclude_unset=True)
        code = changes.get("code")
        if code is not None:
            existing = await self._repo.get_service_by_code(code)
            if existing is not None and existing.id != service.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Код '{code}' уже используется",
                )
        for field, value in changes.items():
            setattr(service, field, value)
        await self._session.commit()
        return service

    async def delete_service(self, service_id: UUID) -> None:
        service = await self._require_service(service_id)
        now = datetime.now(timezone.utc)
        service.deleted_at = now
        service.purge_after = now + timedelta(days=180)
        await self._session.commit()

    # --- Группы происшествий (классы событий) ---
    async def create_event_class(self, payload: EventClassCreate) -> EventClass:
        et = await self._session.get(EventType, payload.event_type_id)
        f1 = await self._session.get(EventFeature1, payload.event_feature_1_id)
        f2 = await self._session.get(EventFeature2, payload.event_feature_2_id)
        f3 = await self._session.get(EventFeature3, payload.event_feature_3_id)
        missing = [
            name
            for name, obj in [
                ("Группа происшествий", et),
                ("Признак 1", f1),
                ("Признак 2", f2),
                ("Признак 3", f3),
            ]
            if obj is None
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Не найдены компоненты классификатора: {', '.join(missing)}",
            )
        if (
            f1.event_type_id != payload.event_type_id
            or f2.event_feature_1_id != payload.event_feature_1_id
            or f3.event_feature_2_id != payload.event_feature_2_id
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Признаки не соответствуют выбранным родительским элементам",
            )

        event_class = EventClass(
            event_number=compute_event_number(et.code, f1.code, f2.code, f3.code),
            event_type_id=payload.event_type_id,
            event_feature_1_id=payload.event_feature_1_id,
            event_feature_2_id=payload.event_feature_2_id,
            event_feature_3_id=payload.event_feature_3_id,
            name=payload.name,
            description=payload.description,
            main_service_id=payload.main_service_id,
            ekp35_type=payload.ekp35_type,
            scenario_code=payload.scenario_code,
            is_active=True,
        )
        event_class.extra_fields = [
            EventClassExtraField(**field.model_dump()) for field in payload.extra_fields
        ]
        self._repo.add(event_class)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Такая комбинация Группы и Признаков уже существует",
            )
        return await self._repo.get_event_class_detail(event_class.id)

    async def update_event_class(
        self, class_id: UUID, payload: EventClassUpdate
    ) -> EventClass:
        event_class = await self._require_event_class(class_id)
        changes = payload.model_dump(exclude_unset=True)
        extra_fields = changes.pop("extra_fields", None)
        for field, value in changes.items():
            setattr(event_class, field, value)
        if extra_fields is not None:
            event_class.extra_fields = [
                EventClassExtraField(**field.model_dump()) for field in extra_fields
            ]
        await self._session.commit()
        return await self._repo.get_event_class_detail(class_id)

    async def _require_service(self, service_id: UUID) -> Service:
        service = await self._repo.get_service(service_id)
        if service is None or service.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Служба не найдена"
            )
        return service

    async def _require_event_class(self, class_id: UUID) -> EventClass:
        event_class = await self._repo.get_event_class(class_id)
        if event_class is None or event_class.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Группа происшествий не найдена",
            )
        return event_class