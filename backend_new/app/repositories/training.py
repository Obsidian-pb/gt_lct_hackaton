from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.content import Scenario, StudyTask, scenario_tasks
from app.models.training import (
    IncidentCard,
    Training,
    TrainingParticipant,
    TrainingSession,
    training_scenarios,
)


class TrainingRepository:
    """Доступ к данным учебного процесса (тренировки, сессии, карточки)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Тренировки ---
    async def list_trainings(self, user_id: UUID | None = None) -> list[Training]:
        query = select(Training).where(Training.deleted_at.is_(None)).order_by(Training.created_at.desc())
        if user_id is not None:
            query = (
                query.join(TrainingParticipant, TrainingParticipant.training_id == Training.id)
                .where(TrainingParticipant.user_id == user_id)
                .distinct()
            )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_training(self, training_id: UUID) -> Training | None:
        result = await self._session.execute(
            select(Training)
            .options(selectinload(Training.scenarios), selectinload(Training.participants))
            .where(Training.id == training_id, Training.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    def add(self, obj) -> None:
        self._session.add(obj)

    async def is_participant(self, training_id: UUID, user_id: UUID) -> bool:
        result = await self._session.execute(
            select(TrainingParticipant.id).where(
                TrainingParticipant.training_id == training_id,
                TrainingParticipant.user_id == user_id,
            )
        )
        return result.first() is not None

    async def get_scenario_ids(self, training_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(training_scenarios.c.scenario_id).where(
                training_scenarios.c.training_id == training_id
            )
        )
        return list(result.scalars().all())

    async def get_scenarios(self, scenario_ids: list[UUID]) -> list[Scenario]:
        if not scenario_ids:
            return []
        result = await self._session.execute(
            select(Scenario).where(Scenario.id.in_(scenario_ids))
        )
        return list(result.scalars().all())

    # --- Сессии ---
    async def get_active_session(self, training_id: UUID, user_id: UUID) -> TrainingSession | None:
        result = await self._session.execute(
            select(TrainingSession).where(
                TrainingSession.training_id == training_id,
                TrainingSession.user_id == user_id,
                TrainingSession.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_session(self, session_id: UUID) -> TrainingSession | None:
        return await self._session.get(TrainingSession, session_id)

    async def list_sessions(self, training_id: UUID) -> list[TrainingSession]:
        result = await self._session.execute(
            select(TrainingSession).where(TrainingSession.training_id == training_id)
        )
        return list(result.scalars().all())

    # --- Задачи и карточки ---
    async def get_tasks_for_training(self, training_id: UUID) -> list[StudyTask]:
        """Все утверждённые учебные задачи сценариев тренировки."""
        result = await self._session.execute(
            select(StudyTask)
            .join(scenario_tasks, scenario_tasks.c.study_task_id == StudyTask.id)
            .join(training_scenarios, training_scenarios.c.scenario_id == scenario_tasks.c.scenario_id)
            .where(
                training_scenarios.c.training_id == training_id,
                StudyTask.status == "approved",
                StudyTask.deleted_at.is_(None),
            )
            .distinct()
        )
        return list(result.scalars().all())

    async def count_cards(self, session_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(IncidentCard).where(IncidentCard.session_id == session_id)
        )
        return int(result.scalar_one())

    async def create_card(
        self, session_id: UUID, study_task_id: UUID, sequence_number: int
    ) -> IncidentCard:
        card = IncidentCard(
            session_id=session_id,
            study_task_id=study_task_id,
            sequence_number=sequence_number,
        )
        self._session.add(card)
        return card

    async def get_card(self, card_id: UUID) -> IncidentCard | None:
        return await self._session.get(IncidentCard, card_id)

    async def list_cards(
        self,
        *,
        training_id: UUID | None = None,
        user_id: UUID | None = None,
        status: str | None = None,
        event_class_id: UUID | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[IncidentCard]:
        query = select(IncidentCard).order_by(IncidentCard.created_at.desc())
        if training_id is not None or user_id is not None:
            query = query.join(
                TrainingSession,
                TrainingSession.id == IncidentCard.session_id,
            )
        if training_id is not None:
            query = query.where(TrainingSession.training_id == training_id)
        if user_id is not None:
            query = query.where(TrainingSession.user_id == user_id)
        if status is not None:
            query = query.where(IncidentCard.status == status)
        if event_class_id is not None:
            query = query.where(IncidentCard.event_class_id == event_class_id)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def dispatcher_cards(self, training_id: UUID, service_id: UUID | None) -> list[IncidentCard]:
        """Карточки для окна 36: ДДС видит все, диспетчер службы — направленные в его службу."""
        query = (
            select(IncidentCard)
            .join(TrainingSession, TrainingSession.id == IncidentCard.session_id)
            .where(TrainingSession.training_id == training_id)
            .order_by(IncidentCard.created_at.desc())
        )
        if service_id is not None:
            query = query.where(IncidentCard.status.in_(["accepted", "routed"]))
            query = query.where(IncidentCard.main_service_id == service_id)
        else:
            query = query.where(IncidentCard.status != "draft")
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_participant_role(self, training_id: UUID, user_id: UUID) -> TrainingParticipant | None:
        result = await self._session.execute(
            select(TrainingParticipant).where(
                TrainingParticipant.training_id == training_id,
                TrainingParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

