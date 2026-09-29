from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.models.reference import ApplicantStatus, ScenarioStatus, TrainingRole
from app.schemas.reference import (
    ApplicantStatusCreate,
    ApplicantStatusOut,
    ApplicantStatusUpdate,
    ScenarioStatusCreate,
    ScenarioStatusOut,
    ScenarioStatusUpdate,
    TrainingRoleCreate,
    TrainingRoleOut,
    TrainingRoleUpdate,
)
from app.services.reference import ReferenceService

write_access = require_roles("system_admin", "admin")


# --- Статусы сценариев (окно 31 ТЗ) -----------------------------------------
scenario_status_router = APIRouter(prefix="/scenario-statuses", tags=["reference"])


@scenario_status_router.get("", response_model=list[ScenarioStatusOut])
async def list_scenario_statuses(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> list[ScenarioStatusOut]:
    items = await ReferenceService(session).list(ScenarioStatus)
    return [ScenarioStatusOut.model_validate(i) for i in items]


@scenario_status_router.post("", response_model=ScenarioStatusOut, status_code=201)
async def create_scenario_status(
    payload: ScenarioStatusCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> ScenarioStatusOut:
    item = await ReferenceService(session).create(ScenarioStatus, payload)
    return ScenarioStatusOut.model_validate(item)


@scenario_status_router.patch("/{item_id}", response_model=ScenarioStatusOut)
async def update_scenario_status(
    item_id: UUID,
    payload: ScenarioStatusUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> ScenarioStatusOut:
    item = await ReferenceService(session).update(ScenarioStatus, item_id, payload)
    return ScenarioStatusOut.model_validate(item)


@scenario_status_router.delete("/{item_id}", status_code=204)
async def delete_scenario_status(
    item_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> None:
    await ReferenceService(session).delete(ScenarioStatus, item_id)


# --- Статусы заявителей (окно 32 ТЗ) ---------------------------------------
applicant_status_router = APIRouter(prefix="/applicant-statuses", tags=["reference"])


@applicant_status_router.get("", response_model=list[ApplicantStatusOut])
async def list_applicant_statuses(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> list[ApplicantStatusOut]:
    items = await ReferenceService(session).list(ApplicantStatus)
    return [ApplicantStatusOut.model_validate(i) for i in items]


@applicant_status_router.post("", response_model=ApplicantStatusOut, status_code=201)
async def create_applicant_status(
    payload: ApplicantStatusCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> ApplicantStatusOut:
    item = await ReferenceService(session).create(ApplicantStatus, payload)
    return ApplicantStatusOut.model_validate(item)


@applicant_status_router.patch("/{item_id}", response_model=ApplicantStatusOut)
async def update_applicant_status(
    item_id: UUID,
    payload: ApplicantStatusUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> ApplicantStatusOut:
    item = await ReferenceService(session).update(ApplicantStatus, item_id, payload)
    return ApplicantStatusOut.model_validate(item)


@applicant_status_router.delete("/{item_id}", status_code=204)
async def delete_applicant_status(
    item_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> None:
    await ReferenceService(session).delete(ApplicantStatus, item_id)


# --- Роли обучающихся (окно 35 ТЗ) ------------------------------------------
training_role_router = APIRouter(prefix="/training-roles", tags=["reference"])


@training_role_router.get("", response_model=list[TrainingRoleOut])
async def list_training_roles(
    session: Annotated[AsyncSession, Depends(get_session)],
    _: CurrentUser,
) -> list[TrainingRoleOut]:
    items = await ReferenceService(session).list(TrainingRole)
    return [TrainingRoleOut.model_validate(i) for i in items]


@training_role_router.post("", response_model=TrainingRoleOut, status_code=201)
async def create_training_role(
    payload: TrainingRoleCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> TrainingRoleOut:
    item = await ReferenceService(session).create(TrainingRole, payload)
    return TrainingRoleOut.model_validate(item)


@training_role_router.patch("/{item_id}", response_model=TrainingRoleOut)
async def update_training_role(
    item_id: UUID,
    payload: TrainingRoleUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> TrainingRoleOut:
    item = await ReferenceService(session).update(TrainingRole, item_id, payload)
    return TrainingRoleOut.model_validate(item)


@training_role_router.delete("/{item_id}", status_code=204)
async def delete_training_role(
    item_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(write_access)],
) -> None:
    await ReferenceService(session).delete(TrainingRole, item_id)