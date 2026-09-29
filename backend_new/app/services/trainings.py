from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.reference import TrainingRole
from app.models.training import Training, TrainingParticipant
from app.repositories.training import TrainingRepository
from app.schemas.trainings import ParticipantIn, TrainingCreate, TrainingUpdate


class TrainingService:
    """Бизнес-логика тренировок (окно 11 ТЗ)."""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = TrainingRepository(session)
        self._session = session

    async def create_training(
        self, payload: TrainingCreate, actor_id: UUID
    ) -> Training:
        await self._validate_scenarios(payload.scenario_ids)
        training = Training(
            title=payload.title,
            description=payload.description,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            difficulty=payload.difficulty,
            mode=payload.mode,
            card_time_limit_seconds=payload.card_time_limit_seconds,
            created_by=actor_id,
        )
        self._repo.add(training)
        await self._session.commit()
        if payload.scenario_ids:
            await self._replace_scenarios(training.id, payload.scenario_ids)
        return await self._require_training(training.id)

    async def update_training(
        self, training_id: UUID, payload: TrainingUpdate
    ) -> Training:
        training = await self._require_training(training_id)
        self._ensure_editable(training)
        changes = payload.model_dump(exclude_unset=True)
        scenario_ids = changes.pop("scenario_ids", None)
        for field, value in changes.items():
            setattr(training, field, value)
        if scenario_ids is not None:
            await self._validate_scenarios(scenario_ids)
            await self._replace_scenarios(training_id, scenario_ids)
        await self._session.commit()
        return await self._require_training(training_id)

    async def activate(self, training_id: UUID) -> Training:
        training = await self._require_training(training_id)
        if training.status != "prepared":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Тренировка в состоянии «{training.status}», активация невозможна",
            )
        scenario_ids = await self._repo.get_scenario_ids(training_id)
        if not scenario_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Нельзя активировать тренировку без учебных сценариев",
            )
        training.status = "active"
        training.started_at = datetime.now(timezone.utc)
        await self._session.commit()
        return await self._require_training(training_id)

    async def finish(self, training_id: UUID) -> Training:
        training = await self._require_training(training_id)
        if training.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Завершить можно только активную тренировку",
            )
        training.status = "finished"
        training.finished_at = datetime.now(timezone.utc)
        await self._session.commit()
        return await self._require_training(training_id)

    async def add_participant(
        self, training_id: UUID, payload: ParticipantIn
    ) -> Training:
        training = await self._require_training(training_id)
        self._ensure_editable(training)
        user = await self._session.get(User, payload.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден"
            )
        role = await self._session.get(TrainingRole, payload.training_role_id)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Роль обучающегося не найдена"
            )
        if role.code == "service_dispatcher" and payload.service_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Для роли «Диспетчер службы» необходимо указать service_id",
            )
        if await self._repo.is_participant(training_id, payload.user_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Обучающийся уже назначен на тренировку",
            )
        self._session.add(
            TrainingParticipant(
                training_id=training_id,
                user_id=payload.user_id,
                training_role_id=payload.training_role_id,
                service_id=payload.service_id,
            )
        )
        await self._session.commit()
        return await self._require_training(training_id)

    async def remove_participant(self, training_id: UUID, user_id: UUID) -> Training:
        training = await self._require_training(training_id)
        self._ensure_editable(training)
        participant = await self._repo.get_participant_role(training_id, user_id)
        if participant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Обучающийся не назначен на тренировку",
            )
        await self._session.delete(participant)
        await self._session.commit()
        return await self._require_training(training_id)

    async def progress(self, training_id: UUID) -> dict:
        await self._require_training(training_id)
        sessions = await self._repo.list_sessions(training_id)
        cards = await self._repo.list_cards(training_id=training_id)
        submitted = [c for c in cards if c.status != "draft"]
        evaluated = [c for c in cards if c.final_score is not None]
        durations = [c.duration_ms for c in cards if c.duration_ms is not None]
        # ФИО участников для отображения в таблице прогресса
        user_ids = list({s.user_id for s in sessions})
        users_by_id: dict[UUID, User] = {}
        if user_ids:
            result = await self._session.execute(
                select(User).where(User.id.in_(user_ids))
            )
            users_by_id = {u.id: u for u in result.scalars().all()}
        participants: list[dict] = []
        for session in sessions:
            user_cards = [c for c in cards if c.session_id == session.id]
            user_submitted = [c for c in user_cards if c.status != "draft"]
            user_durations = [c.duration_ms for c in user_cards if c.duration_ms is not None]
            participants.append(
                {
                    "user_id": str(session.user_id),
                    "session_id": str(session.id),
                    "user_full_name": self._user_full_name(
                        users_by_id.get(session.user_id)
                    ),
                    "total_cards": len(user_cards),
                    "submitted_cards": len(user_submitted),
                    "avg_duration_ms": (
                        round(sum(user_durations) / len(user_durations), 1)
                        if user_durations
                        else None
                    ),
                }
            )
        return {
            "training_id": str(training_id),
            "total_cards": len(cards),
            "submitted_cards": len(submitted),
            "evaluated_cards": len(evaluated),
            "avg_duration_ms": (
                round(sum(durations) / len(durations), 1) if durations else None
            ),
            "participants": participants,
        }

    async def _replace_scenarios(self, training_id: UUID, scenario_ids: list[UUID]) -> None:
        from app.models.training import training_scenarios

        await self._session.execute(
            training_scenarios.delete().where(
                training_scenarios.c.training_id == training_id
            )
        )
        for order, scenario_id in enumerate(scenario_ids):
            await self._session.execute(
                training_scenarios.insert().values(
                    training_id=training_id,
                    scenario_id=scenario_id,
                    sort_order=order,
                )
            )
        await self._session.commit()

    async def _validate_scenarios(self, scenario_ids: list[UUID]) -> None:
        if not scenario_ids:
            return
        scenarios = await self._repo.get_scenarios(scenario_ids)
        if len(scenarios) != len(set(scenario_ids)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Один из сценариев не найден",
            )
        for scenario in scenarios:
            if scenario.scenario_status_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Сценарий «{scenario.topic}» не утверждён",
                )

    async def _require_training(self, training_id: UUID) -> Training:
        training = await self._repo.get_training(training_id)
        if training is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Тренировка не найдена"
            )
        return training

    @staticmethod
    def _ensure_editable(training: Training) -> None:
        if training.status == "finished":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Завершённую тренировку нельзя изменять",
            )

    @staticmethod
    def _user_full_name(user: User | None) -> str | None:
        """ФИО пользователя одним полем (last_name first_name middle_name)."""
        if user is None:
            return None
        return " ".join(p for p in (user.last_name, user.first_name, user.middle_name) if p)