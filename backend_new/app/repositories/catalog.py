from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import (
    ClassifierVersion,
    EventClass,
    EventClassExtraField,
    EventFeature1,
    EventFeature2,
    EventFeature3,
    EventType,
    Service,
)


class CatalogRepository:
    """Доступ к данным классификатора происшествий и служб."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Службы ---
    async def list_services(self) -> list[Service]:
        result = await self._session.execute(
            select(Service).where(Service.deleted_at.is_(None)).order_by(Service.name)
        )
        return list(result.scalars().all())

    async def get_service(self, service_id: UUID) -> Service | None:
        return await self._session.get(Service, service_id)

    async def get_service_by_code(self, code: str) -> Service | None:
        result = await self._session.execute(select(Service).where(Service.code == code))
        return result.scalar_one_or_none()

    def add(self, obj) -> None:
        self._session.add(obj)

    # --- Классификатор ---
    async def list_event_types(self) -> list[EventType]:
        result = await self._session.execute(select(EventType).order_by(EventType.code))
        return list(result.scalars().all())

    async def list_features_1(self, event_type_id: UUID | None = None) -> list[EventFeature1]:
        query = select(EventFeature1).order_by(EventFeature1.code)
        if event_type_id is not None:
            query = query.where(EventFeature1.event_type_id == event_type_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_features_2(self, feature_1_id: UUID | None = None) -> list[EventFeature2]:
        query = select(EventFeature2).order_by(EventFeature2.code)
        if feature_1_id is not None:
            query = query.where(EventFeature2.event_feature_1_id == feature_1_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_features_3(self, feature_2_id: UUID | None = None) -> list[EventFeature3]:
        query = select(EventFeature3).order_by(EventFeature3.code)
        if feature_2_id is not None:
            query = query.where(EventFeature3.event_feature_2_id == feature_2_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_event_classes(self) -> list[EventClass]:
        result = await self._session.execute(
            select(EventClass)
            .where(EventClass.deleted_at.is_(None))
            .order_by(EventClass.event_number)
        )
        return list(result.scalars().all())

    async def get_event_class(self, class_id: UUID) -> EventClass | None:
        return await self._session.get(EventClass, class_id)

    async def get_event_class_detail(self, class_id: UUID) -> EventClass | None:
        result = await self._session.execute(
            select(EventClass)
            .options(selectinload(EventClass.extra_fields))
            .where(EventClass.id == class_id)
        )
        return result.scalar_one_or_none()

    async def get_extra_fields(self, class_id: UUID) -> list[EventClassExtraField]:
        result = await self._session.execute(
            select(EventClassExtraField)
            .where(EventClassExtraField.event_class_id == class_id)
            .order_by(EventClassExtraField.sort_order)
        )
        return list(result.scalars().all())

    async def list_classifier_versions(self) -> list[ClassifierVersion]:
        result = await self._session.execute(
            select(ClassifierVersion).order_by(ClassifierVersion.version_number.desc())
        )
        return list(result.scalars().all())