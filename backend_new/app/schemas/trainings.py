from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.scenarios import ScenarioOut


class TrainingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    difficulty: str = Field(default="medium", pattern="^(low|medium|high|adaptive)$")
    mode: str = Field(default="training", pattern="^(training|testing)$")
    card_time_limit_seconds: int = Field(default=30, ge=1)
    scenario_ids: list[UUID] = Field(default_factory=list)


class TrainingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    difficulty: str | None = Field(default=None, pattern="^(low|medium|high|adaptive)$")
    mode: str | None = Field(default=None, pattern="^(training|testing)$")
    card_time_limit_seconds: int | None = Field(default=None, ge=1)
    scenario_ids: list[UUID] | None = None


class ParticipantIn(BaseModel):
    user_id: UUID
    training_role_id: UUID
    service_id: UUID | None = None


class ParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    training_id: UUID
    user_id: UUID
    training_role_id: UUID
    service_id: UUID | None


class TrainingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    difficulty: str
    mode: str
    status: str
    card_time_limit_seconds: int
    created_by: UUID | None
    created_at: datetime
    scenario_count: int = 0
    participant_count: int = 0


class TrainingDetailOut(TrainingOut):
    scenarios: list[ScenarioOut] = []
    participants: list[ParticipantOut] = []


class TrainingProgressOut(BaseModel):
    training_id: UUID
    total_cards: int
    submitted_cards: int
    evaluated_cards: int
    avg_duration_ms: float | None = None
    participants: list[dict[str, Any]] = []