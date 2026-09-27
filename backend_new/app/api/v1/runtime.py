from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.db.session import get_session
from app.repositories.training import TrainingRepository
from app.schemas.cards import (
    AcceptCallIn,
    CardContentUpdate,
    CardOut,
    NextTaskOut,
    SessionOut,
)
from app.services.runtime import RuntimeService

router = APIRouter(tags=["runtime"])


class StartSessionIn(BaseModel):
    training_id: UUID


class RouteCardIn(BaseModel):
    service_id: UUID | None = None


@router.post("/sessions/start", response_model=SessionOut, summary="Старт сессии (окно 17 ТЗ)")
async def start_session(
    payload: StartSessionIn,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionOut:
    item = await RuntimeService(session).start_session(payload.training_id, current_user)
    return SessionOut.model_validate(item)


@router.post("/sessions/{session_id}/finish", response_model=SessionOut, summary="Завершение сессии")
async def finish_session(
    session_id: UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SessionOut:
    item = await RuntimeService(session).finish_session(session_id, current_user)
    return SessionOut.model_validate(item)


@router.get("/sessions/{session_id}/next-task", response_model=NextTaskOut, summary="Выдача следующей учебной задачи")
async def next_task(
    session_id: UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NextTaskOut:
    return await RuntimeService(session).next_task(session_id, current_user)


@router.post("/sessions/{session_id}/accept-call", response_model=CardOut, summary="Принять вызов — создать карточку")
async def accept_call(
    session_id: UUID,
    payload: AcceptCallIn,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardOut:
    card = await RuntimeService(session).accept_call(
        session_id, payload.study_task_id, current_user
    )
    return CardOut.model_validate(card)


@router.patch("/cards/{card_id}/content", response_model=CardOut, summary="Сохранение черновика карточки")
async def save_card_content(
    card_id: UUID,
    payload: CardContentUpdate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardOut:
    card = await RuntimeService(session).save_card(card_id, payload.content, current_user)
    return CardOut.model_validate(card)


@router.post("/cards/{card_id}/submit", response_model=CardOut, summary="Отправить карточку (сохранить и сверить с эталоном)")
async def submit_card(
    card_id: UUID,
    payload: CardContentUpdate,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardOut:
    card = await RuntimeService(session).submit_card(card_id, payload.content, current_user)
    return CardOut.model_validate(card)


# --- Окно 36: контроль карточек диспетчерами ---
@router.get("/dispatcher/cards", response_model=list[CardOut], summary="Карточки в работе (окно 36 ТЗ)")
async def dispatcher_cards(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    training_id: UUID,
) -> list[CardOut]:
    repo = TrainingRepository(session)
    participant = await repo.get_participant_role(training_id, current_user.id)
    if participant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Вы не участвуете в этой тренировке",
        )
    from app.models.reference import TrainingRole

    role = await session.get(TrainingRole, participant.training_role_id)
    service_id = None
    if role is not None and role.code == "service_dispatcher":
        service_id = participant.service_id
    elif role is None or role.code == "operator_112":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Окно контроля карточек доступно диспетчерам",
        )
    cards = await repo.dispatcher_cards(training_id, service_id)
    return [CardOut.model_validate(c) for c in cards]


@router.post("/cards/{card_id}/accept", response_model=CardOut, summary="Принять карточку (ДДС)")
async def accept_card(
    card_id: UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardOut:
    card = await RuntimeService(session).accept_card(card_id, current_user)
    return CardOut.model_validate(card)


@router.post("/cards/{card_id}/route", response_model=CardOut, summary="Направить карточку в службу (ДДС)")
async def route_card(
    card_id: UUID,
    payload: RouteCardIn,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardOut:
    card = await RuntimeService(session).route_card(
        card_id, current_user, payload.service_id
    )
    return CardOut.model_validate(card)


@router.post("/cards/{card_id}/process", response_model=CardOut, summary="Отработать карточку (диспетчер службы)")
async def process_card(
    card_id: UUID,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardOut:
    card = await RuntimeService(session).process_card(card_id, current_user)
    return CardOut.model_validate(card)