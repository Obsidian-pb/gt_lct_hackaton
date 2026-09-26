from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ServiceBase(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class ServiceOut(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class EventTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: int
    name: str
    description: str | None


class EventFeature1Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type_id: UUID
    code: int
    statistics_name: str
    operator_label: str | None


class EventFeature2Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_feature_1_id: UUID
    code: int
    name: str
    description: str | None


class EventFeature3Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_feature_2_id: UUID
    code: int
    name: str
    description: str | None


class EventClassExtraFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_class_id: UUID
    code: str
    label: str
    field_type: str
    required: bool
    options: list[Any]
    sort_order: int


class EventClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_number: int
    event_type_id: UUID
    event_feature_1_id: UUID
    event_feature_2_id: UUID
    event_feature_3_id: UUID
    name: str
    description: str | None
    main_service_id: UUID | None
    is_active: bool


class EventClassDetailOut(EventClassOut):
    extra_fields: list[EventClassExtraFieldOut] = []


class EventClassCreate(BaseModel):
    event_type_id: UUID
    event_feature_1_id: UUID
    event_feature_2_id: UUID
    event_feature_3_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    main_service_id: UUID | None = None
    ekp35_type: str | None = None
    scenario_code: str | None = None
    extra_fields: list[EventClassExtraFieldOut] = []


class EventClassUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    main_service_id: UUID | None = None
    is_active: bool | None = None
    extra_fields: list[EventClassExtraFieldOut] | None = None


class ClassifierVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    name: str
    source_name: str | None
    is_active: bool
    published_at: Any | None