from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    training_id: UUID
    user_id: UUID
    status: str
    started_at: datetime
    finished_at: datetime | None


class NextTaskOut(BaseModel):
    study_task_id: UUID
    caller_message: str
    aon_phone: str | None
    provided_phone: str | None
    scene_phone: str | None
    caller_full_name: str | None
    difficulty: int
    address: dict[str, Any] = Field(default_factory=dict)


class AcceptCallIn(BaseModel):
    study_task_id: UUID


class CardContentUpdate(BaseModel):
    content: dict[str, Any]


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    study_task_id: UUID
    sequence_number: int
    status: str
    content: dict[str, Any]
    event_type_id: UUID | None
    event_feature_1_id: UUID | None
    event_feature_2_id: UUID | None
    event_feature_3_id: UUID | None
    event_class_id: UUID | None
    main_service_id: UUID | None
    machine_score: float | None
    ai_score: float | None
    final_score: float | None
    evaluated_by: UUID | None
    evaluated_at: datetime | None
    created_at: datetime
    submitted_at: datetime | None
    accepted_at: datetime | None
    routed_at: datetime | None
    processed_at: datetime | None
    duration_ms: int | None


class CardGradeIn(BaseModel):
    final_score: float = Field(ge=0, le=100)