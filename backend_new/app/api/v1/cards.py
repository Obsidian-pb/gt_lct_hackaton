from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.repositories.training import TrainingRepository
from app.schemas.cards import CardGradeIn, CardOut
from app.services.runtime import RuntimeService

router = APIRouter(prefix="/cards", tags=["cards"])
teacher_access = require_roles("system_admin", "admin", "teacher")


@router.get("", response_model=list[CardOut], summary="Список учебных карточек (окно 15 ТЗ)")
async def list_cards(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    training_id: UUID | None = None,
    user_id: UUID | None = None,
    card_status: str | None = None,
    event_class_id: UUID | None = None,
) -> list[CardOut]:
    cards = await TrainingRepository(session).list_cards(
        training_id=training_id,
        user_id=user_id,
        status=card_status,
        event_class_id=event_class_id,
    )
    return [CardOut.model_validate(c) for c in cards]


@router.get("/{card_id}", response_model=CardOut, summary="Карточка происшествия (окно 14 ТЗ)")
async def get_card(
    card_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardOut:
    card = await TrainingRepository(session).get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена"
        )
    return CardOut.model_validate(card)


@router.post("/{card_id}/grade", response_model=CardOut, summary="Итоговая оценка преподавателя")
async def grade_card(
    card_id: UUID,
    payload: CardGradeIn,
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(teacher_access)],
) -> CardOut:
    card = await RuntimeService(session)._repo.get_card(card_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена"
        )
    from datetime import datetime, timezone

    card.final_score = payload.final_score
    card.evaluated_by = current_user.id
    card.evaluated_at = datetime.now(timezone.utc)
    await session.commit()
    return CardOut.model_validate(card)