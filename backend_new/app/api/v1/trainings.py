from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.models.training import Training
from app.repositories.training import TrainingRepository
from app.schemas.scenarios import ScenarioOut
from app.schemas.trainings import (
    ParticipantIn,
    ParticipantOut,
    TrainingCreate,
    TrainingDetailOut,
    TrainingOut,
    TrainingProgressOut,
    TrainingUpdate,
)
from app.services.trainings import TrainingService

router = APIRouter(prefix="/trainings", tags=["trainings"])
teacher_access = require_roles("system_admin", "admin", "teacher")

STAFF_ROLES = {"system_admin", "admin", "teacher"}


def _is_staff(user) -> bool:
    return bool({role.code for role in user.roles}.intersection(STAFF_ROLES))


def training_to_out(training: Training) -> TrainingOut:
    data = TrainingOut.model_validate(training).model_dump()
    data["scenario_count"] = len(training.scenarios)
    data["participant_count"] = len(training.participants)
    return TrainingOut(**data)


def training_to_detail(training: Training) -> TrainingDetailOut:
    base = training_to_out(training)
    return TrainingDetailOut(
        **base.model_dump(),
        scenarios=[ScenarioOut.model_validate(s) for s in training.scenarios],
        participants=[ParticipantOut.model_validate(p) for p in training.participants],
    )


@router.get("", response_model=list[TrainingOut], summary="Список тренировок (окно 10 ТЗ)")
async def list_trainings(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[TrainingOut]:
    if _is_staff(current_user):
        trainings = await TrainingRepository(session).list_trainings()
    else:
        # Обучающийся видит только назначенные ему тренировки
        trainings = await TrainingRepository(session).list_trainings(current_user.id)
    return [training_to_out(t) for t in trainings]


@router.post("", response_model=TrainingDetailOut, status_code=201, summary="Создание тренировки")
async def create_training(
    payload: TrainingCreate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(teacher_access)],
) -> TrainingDetailOut:
    training = await TrainingService(session).create_training(payload, current_user.id)
    return training_to_detail(training)


@router.get("/{training_id}", response_model=TrainingDetailOut, summary="Тренировка (окно 11 ТЗ)")
async def get_training(
    training_id: UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TrainingDetailOut:
    training = await TrainingRepository(session).get_training(training_id)
    if training is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Тренировка не найдена"
        )
    if not _is_staff(current_user):
        if not await TrainingRepository(session).is_participant(training_id, current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Вы не назначены на эту тренировку",
            )
    return training_to_detail(training)


@router.patch("/{training_id}", response_model=TrainingDetailOut, summary="Изменение тренировки")
async def update_training(
    training_id: UUID,
    payload: TrainingUpdate,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> TrainingDetailOut:
    training = await TrainingService(session).update_training(training_id, payload)
    return training_to_detail(training)


@router.delete("/{training_id}", status_code=204, summary="Удаление тренировки")
async def delete_training(
    training_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> None:
    training = await TrainingRepository(session).get_training(training_id)
    if training is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Тренировка не найдена"
        )
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    training.deleted_at = now
    training.purge_after = now + timedelta(days=180)
    await session.commit()


@router.post("/{training_id}/activate", response_model=TrainingDetailOut, summary="Активация тренировки")
async def activate_training(
    training_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> TrainingDetailOut:
    training = await TrainingService(session).activate(training_id)
    return training_to_detail(training)


@router.post("/{training_id}/finish", response_model=TrainingDetailOut, summary="Завершение тренировки")
async def finish_training(
    training_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> TrainingDetailOut:
    training = await TrainingService(session).finish(training_id)
    return training_to_detail(training)


@router.post("/{training_id}/participants", response_model=TrainingDetailOut, status_code=201, summary="Назначение обучающегося с ролью")
async def add_participant(
    training_id: UUID,
    payload: ParticipantIn,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> TrainingDetailOut:
    training = await TrainingService(session).add_participant(training_id, payload)
    return training_to_detail(training)


@router.delete("/{training_id}/participants/{user_id}", response_model=TrainingDetailOut, summary="Снятие обучающегося")
async def remove_participant(
    training_id: UUID,
    user_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> TrainingDetailOut:
    training = await TrainingService(session).remove_participant(training_id, user_id)
    return training_to_detail(training)


@router.get("/{training_id}/progress", response_model=TrainingProgressOut, summary="Прогресс тренировки в реальном времени")
async def training_progress(
    training_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> TrainingProgressOut:
    data = await TrainingService(session).progress(training_id)
    return TrainingProgressOut(**data)