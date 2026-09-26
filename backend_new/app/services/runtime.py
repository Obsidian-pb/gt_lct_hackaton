from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.content import StudyTask
from app.models.training import IncidentCard, TrainingSession
from app.repositories.content import ContentRepository
from app.repositories.training import TrainingRepository
from app.schemas.cards import NextTaskOut


def machine_score_card(etalon: dict[str, Any], content: dict[str, Any]) -> tuple[Decimal, dict]:
    """Машинное сравнение карточки с эталоном: доля совпавших полей (0-100%)."""
    details: dict[str, Any] = {}
    total = len(etalon)
    matched = 0
    for key, expected in etalon.items():
        actual = content.get(key)
        ok = False
        if actual is not None and expected is not None:
            ok = str(actual).strip().lower() == str(expected).strip().lower()
        details[key] = {"expected": expected, "actual": actual, "match": ok}
        matched += int(ok)
    score = round(matched / total * 100, 2) if total else 0
    return Decimal(str(score)), details


class RuntimeService:
    """Бизнес-логика эмулятора АРМ-112 (окна 17, 36 ТЗ)."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = TrainingRepository(session)
        self._content = ContentRepository(session)
        self._session = session

    # --- Сессии ---
    async def start_session(self, training_id: UUID, user: User) -> TrainingSession:
        training = await self._require_training(training_id)
        if training.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Тренировка не активна — старт невозможен",
            )
        if not await self._repo.is_participant(training_id, user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Вы не назначены на эту тренировку",
            )
        existing = await self._repo.get_active_session(training_id, user.id)
        if existing is not None:
            return existing
        session = TrainingSession(training_id=training_id, user_id=user.id)
        self._session.add(session)
        await self._session.commit()
        return session

    async def finish_session(self, session_id: UUID, user: User) -> TrainingSession:
        session = await self._repo.get_session(session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена"
            )
        session.status = "finished"
        session.finished_at = datetime.now(timezone.utc)
        await self._session.commit()
        return session

    # --- Выдача задач ---
    async def next_task(self, session_id: UUID, user: User) -> NextTaskOut:
        session = await self._require_own_session(session_id, user)
        training = await self._require_training(session.training_id)
        if training.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Тренировка завершена"
            )
        used_task_ids = {
            card.study_task_id
            for card in await self._repo.list_cards(training_id=training.id)
            if card.session_id == session.id
        }
        candidates = [t for t in await self._repo.get_tasks_for_training(training.id) if t.id not in used_task_ids]
        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Все учебные задачи тренировки выполнены",
            )
        task = random.choice(candidates)
        return NextTaskOut(
            study_task_id=task.id,
            caller_message=task.caller_message,
            aon_phone=task.aon_phone,
            provided_phone=task.provided_phone,
            scene_phone=task.scene_phone,
            caller_full_name=task.caller_full_name,
            difficulty=task.difficulty,
            address={
                "street": task.street,
                "house": task.house,
                "locality": task.locality,
                "district": task.district,
                "descriptive_address": task.descriptive_address,
            },
        )

    # --- Карточки: оператор-112 ---
    async def accept_call(
        self, session_id: UUID, study_task_id: UUID, user: User
    ) -> IncidentCard:
        session = await self._require_own_session(session_id, user)
        task = await self._content.get_task(study_task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Учебная задача не найдена"
            )
        sequence = await self._repo.count_cards(session.id) + 1
        card = await self._repo.create_card(session.id, task.id, sequence)
        card.event_class_id = task.event_class_id
        card.main_service_id = task.main_service_id
        await self._session.commit()
        return card

    async def save_card(self, card_id: UUID, content: dict, user: User) -> IncidentCard:
        card = await self._require_own_card(card_id, user)
        if card.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Карточка уже принята и не может быть изменена",
            )
        card.content = content
        await self._session.commit()
        return card

    async def submit_card(self, card_id: UUID, content: dict, user: User) -> IncidentCard:
        card = await self._require_own_card(card_id, user)
        if card.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Карточка уже отправлена",
            )
        card.content = content
        card.status = "submitted"
        card.submitted_at = datetime.now(timezone.utc)
        card.duration_ms = int((card.submitted_at - card.created_at).total_seconds() * 1000)
        task = await self._content.get_task(card.study_task_id)
        if task is not None and task.etalon is not None:
            card.machine_score, card.machine_eval_details = machine_score_card(
                task.etalon.content, content
            )
        await self._session.commit()
        return card

    # --- Окно 36: диспетчеры ---
    async def accept_card(self, card_id: UUID, user: User) -> IncidentCard:
        card = await self._require_card_in_training(card_id, user, roles=("dispatcher_dds",))
        if card.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Принять можно только отправленную карточку",
            )
        card.status = "accepted"
        card.accepted_at = datetime.now(timezone.utc)
        await self._session.commit()
        return card

    async def route_card(
        self, card_id: UUID, user: User, service_id: UUID | None = None
    ) -> IncidentCard:
        card = await self._require_card_in_training(card_id, user, roles=("dispatcher_dds",))
        if card.status != "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Направить в службу можно только принятую карточку",
            )
        if service_id is not None:
            card.main_service_id = service_id
        if card.main_service_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Не указана служба для направления",
            )
        card.status = "routed"
        card.routed_at = datetime.now(timezone.utc)
        await self._session.commit()
        return card

    async def process_card(self, card_id: UUID, user: User) -> IncidentCard:
        card = await self._require_card_in_training(
            card_id, user, roles=("service_dispatcher",)
        )
        if card.status != "routed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Отработать можно только направленную карточку",
            )
        session = await self._repo.get_session(card.session_id)
        participant = await self._repo.get_participant_role(session.training_id, user.id)
        if participant.service_id != card.main_service_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Карточка направлена в другую службу",
            )
        card.status = "processed"
        card.processed_at = datetime.now(timezone.utc)
        await self._session.commit()
        return card

    # --- Вспомогательные проверки ---
    async def _require_training(self, training_id: UUID):
        training = await self._repo.get_training(training_id)
        if training is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Тренировка не найдена"
            )
        return training

    async def _require_own_session(self, session_id: UUID, user: User) -> TrainingSession:
        session = await self._repo.get_session(session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена"
            )
        if session.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Сессия завершена"
            )
        return session

    async def _require_own_card(self, card_id: UUID, user: User) -> IncidentCard:
        card = await self._repo.get_card(card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена"
            )
        session = await self._repo.get_session(card.session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Это не ваша карточка",
            )
        return card

    async def _training_of(self, card: IncidentCard) -> UUID:
        session = await self._repo.get_session(card.session_id)
        return session.training_id

    async def _require_card_in_training(
        self, card_id: UUID, user: User, roles: tuple[str, ...]
    ) -> IncidentCard:
        card = await self._repo.get_card(card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Карточка не найдена"
            )
        session = await self._repo.get_session(card.session_id)
        participant = await self._repo.get_participant_role(session.training_id, user.id)
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Вы не участвуете в этой тренировке",
            )
        from app.models.reference import TrainingRole

        role = await self._session.get(TrainingRole, participant.training_role_id)
        if role is None or role.code not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Для этого действия нужна роль: {', '.join(roles)}",
            )
        return card