from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tasks import StudyTaskOut


class ScenarioCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=255)
    description: str | None = None
    scenario_status_id: UUID | None = None


class ScenarioUpdate(BaseModel):
    topic: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    scenario_status_id: UUID | None = None


class TaskLinkIn(BaseModel):
    study_task_id: UUID


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic: str
    description: str | None
    scenario_status_id: UUID | None
    created_by: UUID | None
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime
    task_count: int = 0


class ScenarioDetailOut(ScenarioOut):
    tasks: list[StudyTaskOut] = []