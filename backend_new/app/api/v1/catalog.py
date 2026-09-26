from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    ClassifierVersionOut,
    EventClassCreate,
    EventClassDetailOut,
    EventClassExtraFieldOut,
    EventClassOut,
    EventClassUpdate,
    EventFeature1Out,
    EventFeature2Out,
    EventFeature3Out,
    EventTypeOut,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
)
from app.services.catalog import CatalogService

router = APIRouter(tags=["catalog"])
write_access = require_roles("system_admin", "admin")


# --- Службы (окно 34 ТЗ) ---
@router.get("/services", response_model=list[ServiceOut], summary="Список служб")
async def list_services(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> list[ServiceOut]:
    services = await CatalogRepository(session).list_services()
    return [ServiceOut.model_validate(s) for s in services]


@router.post("/services", response_model=ServiceOut, status_code=201)
async def create_service(
    payload: ServiceCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> ServiceOut:
    service = await CatalogService(session).create_service(payload)
    return ServiceOut.model_validate(service)


@router.patch("/services/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: UUID,
    payload: ServiceUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> ServiceOut:
    service = await CatalogService(session).update_service(service_id, payload)
    return ServiceOut.model_validate(service)


@router.delete("/services/{service_id}", status_code=204)
async def delete_service(
    service_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> None:
    await CatalogService(session).delete_service(service_id)


# --- Классификатор происшествий (окна 28-29 ТЗ) ---
@router.get("/classifier/event-types", response_model=list[EventTypeOut], summary="Группы происшествий (код Г)")
async def list_event_types(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> list[EventTypeOut]:
    items = await CatalogRepository(session).list_event_types()
    return [EventTypeOut.model_validate(i) for i in items]


@router.get("/classifier/features-1", response_model=list[EventFeature1Out], summary="Признак 1")
async def list_features_1(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    event_type_id: UUID | None = None,
) -> list[EventFeature1Out]:
    items = await CatalogRepository(session).list_features_1(event_type_id)
    return [EventFeature1Out.model_validate(i) for i in items]


@router.get("/classifier/features-2", response_model=list[EventFeature2Out], summary="Признак 2")
async def list_features_2(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_1_id: UUID | None = None,
) -> list[EventFeature2Out]:
    items = await CatalogRepository(session).list_features_2(feature_1_id)
    return [EventFeature2Out.model_validate(i) for i in items]


@router.get("/classifier/features-3", response_model=list[EventFeature3Out], summary="Признак 3")
async def list_features_3(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    feature_2_id: UUID | None = None,
) -> list[EventFeature3Out]:
    items = await CatalogRepository(session).list_features_3(feature_2_id)
    return [EventFeature3Out.model_validate(i) for i in items]


@router.get("/classifier/versions", response_model=list[ClassifierVersionOut], summary="Версии классификатора")
async def list_classifier_versions(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> list[ClassifierVersionOut]:
    items = await CatalogRepository(session).list_classifier_versions()
    return [ClassifierVersionOut.model_validate(i) for i in items]


# --- Группы происшествий с доп. полями (окна 28-29 ТЗ) ---
@router.get("/event-groups", response_model=list[EventClassOut], summary="Список групп происшествий")
async def list_event_groups(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> list[EventClassOut]:
    items = await CatalogRepository(session).list_event_classes()
    return [EventClassOut.model_validate(i) for i in items]


@router.get("/event-groups/{group_id}", response_model=EventClassDetailOut, summary="Сведения о группе происшествий")
async def get_event_group(
    group_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> EventClassDetailOut:
    item = await CatalogRepository(session).get_event_class_detail(group_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Группа происшествий не найдена"
        )
    return EventClassDetailOut.model_validate(item)


@router.post("/event-groups", response_model=EventClassDetailOut, status_code=201)
async def create_event_group(
    payload: EventClassCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> EventClassDetailOut:
    item = await CatalogService(session).create_event_class(payload)
    return EventClassDetailOut.model_validate(item)


@router.patch("/event-groups/{group_id}", response_model=EventClassDetailOut)
async def update_event_group(
    group_id: UUID,
    payload: EventClassUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> EventClassDetailOut:
    item = await CatalogService(session).update_event_class(group_id, payload)
    return EventClassDetailOut.model_validate(item)