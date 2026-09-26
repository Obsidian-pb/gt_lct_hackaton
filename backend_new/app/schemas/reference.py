from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScenarioStatusBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    sort_order: int = 0
    is_active: bool = True


class ScenarioStatusCreate(ScenarioStatusBase):
    pass


class ScenarioStatusUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    sort_order: int | None = None
    is_active: bool | None = None


class ScenarioStatusOut(ScenarioStatusBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class ApplicantStatusBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    sort_order: int = 0
    is_active: bool = True


class ApplicantStatusCreate(ApplicantStatusBase):
    pass


class ApplicantStatusUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    sort_order: int | None = None
    is_active: bool | None = None


class ApplicantStatusOut(ApplicantStatusBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class TrainingRoleBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    is_active: bool = True


class TrainingRoleCreate(TrainingRoleBase):
    pass


class TrainingRoleUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    is_active: bool | None = None


class TrainingRoleOut(TrainingRoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID