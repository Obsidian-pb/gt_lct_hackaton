from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.catalog import ServiceOut


class ExtraFieldSchemaIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=255)
    field_type: str = Field(pattern="^(text|number|boolean|select|date)$")
    required: bool = False
    options: list[Any] = Field(default_factory=list)
    sort_order: int = 0


class ExtraFieldSchemaOut(ExtraFieldSchemaIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class StudyTaskCreate(BaseModel):
    difficulty: int = Field(ge=1, le=5)
    caller_message: str = Field(min_length=1)
    aon_phone: str | None = Field(default=None, max_length=32)
    provided_phone: str | None = Field(default=None, max_length=32)
    scene_phone: str | None = Field(default=None, max_length=32)
    caller_full_name: str | None = Field(default=None, max_length=255)
    applicant_status_id: UUID | None = None

    # Адрес
    country: str | None = Field(default=None, max_length=128)
    federal_subject: str | None = Field(default=None, max_length=255)
    locality: str | None = Field(default=None, max_length=255)
    address_object: str | None = Field(default=None, max_length=255)
    administrative_district: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=255)
    street: str | None = Field(default=None, max_length=255)
    house: str | None = Field(default=None, max_length=32)
    building: str | None = Field(default=None, max_length=32)
    structure: str | None = Field(default=None, max_length=32)
    apartment: str | None = Field(default=None, max_length=32)
    entrance: str | None = Field(default=None, max_length=32)
    floor: str | None = Field(default=None, max_length=32)
    intercom_code: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    descriptive_address: str | None = None

    incident_description: str | None = None
    has_victims: bool = False
    no_scene_refusal: bool = False
    no_access: bool = False
    no_contact: bool = False
    call_dropped: bool = False

    event_type_id: UUID | None = None
    event_feature_1_id: UUID | None = None
    event_feature_2_id: UUID | None = None
    event_feature_3_id: UUID | None = None
    event_class_id: UUID | None = None
    extra_fields: dict[str, Any] = Field(default_factory=dict)
    main_service_id: UUID | None = None
    service_ids: list[UUID] = Field(default_factory=list)

    # Эталон: содержимое эталонной карточки (заполненное учебное задание)
    etalon_content: dict[str, Any] = Field(default_factory=dict)
    field_schema: list[Any] = Field(default_factory=list)
    # Схема дополнительных полей задачи (значения — в extra_fields)
    extra_field_schemas: list[ExtraFieldSchemaIn] = Field(default_factory=list)


class StudyTaskUpdate(BaseModel):
    difficulty: int | None = Field(default=None, ge=1, le=5)
    caller_message: str | None = Field(default=None, min_length=1)
    aon_phone: str | None = Field(default=None, max_length=32)
    provided_phone: str | None = Field(default=None, max_length=32)
    scene_phone: str | None = Field(default=None, max_length=32)
    caller_full_name: str | None = Field(default=None, max_length=255)
    applicant_status_id: UUID | None = None
    country: str | None = Field(default=None, max_length=128)
    federal_subject: str | None = Field(default=None, max_length=255)
    locality: str | None = Field(default=None, max_length=255)
    address_object: str | None = Field(default=None, max_length=255)
    administrative_district: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=255)
    street: str | None = Field(default=None, max_length=255)
    house: str | None = Field(default=None, max_length=32)
    building: str | None = Field(default=None, max_length=32)
    structure: str | None = Field(default=None, max_length=32)
    apartment: str | None = Field(default=None, max_length=32)
    entrance: str | None = Field(default=None, max_length=32)
    floor: str | None = Field(default=None, max_length=32)
    intercom_code: str | None = Field(default=None, max_length=64)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    descriptive_address: str | None = None
    incident_description: str | None = None
    has_victims: bool | None = None
    no_scene_refusal: bool | None = None
    no_access: bool | None = None
    no_contact: bool | None = None
    call_dropped: bool | None = None
    event_type_id: UUID | None = None
    event_feature_1_id: UUID | None = None
    event_feature_2_id: UUID | None = None
    event_feature_3_id: UUID | None = None
    event_class_id: UUID | None = None
    extra_fields: dict[str, Any] | None = None
    main_service_id: UUID | None = None
    service_ids: list[UUID] | None = None
    etalon_content: dict[str, Any] | None = None
    field_schema: list[Any] | None = None
    extra_field_schemas: list[ExtraFieldSchemaIn] | None = None


class StudyTaskApproveRequest(BaseModel):
    approve: bool = True
    comment: str | None = None


class StudyTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    difficulty: int
    caller_message: str
    aon_phone: str | None
    provided_phone: str | None
    scene_phone: str | None
    caller_full_name: str | None
    applicant_status_id: UUID | None
    country: str | None
    federal_subject: str | None
    locality: str | None
    address_object: str | None
    administrative_district: str | None
    district: str | None
    street: str | None
    house: str | None
    building: str | None
    structure: str | None
    apartment: str | None
    entrance: str | None
    floor: str | None
    intercom_code: str | None
    latitude: float | None
    longitude: float | None
    descriptive_address: str | None
    incident_description: str | None
    has_victims: bool
    no_scene_refusal: bool
    no_access: bool
    no_contact: bool
    call_dropped: bool
    event_type_id: UUID | None
    event_feature_1_id: UUID | None
    event_feature_2_id: UUID | None
    event_feature_3_id: UUID | None
    event_class_id: UUID | None
    extra_fields: dict[str, Any]
    main_service_id: UUID | None
    status: str
    created_by: UUID | None
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime
    services: list[ServiceOut] = []
    etalon_content: dict[str, Any] | None = None
    field_schema: list[Any] | None = None
    extra_field_schemas: list[ExtraFieldSchemaOut] = []


def task_to_out(task) -> StudyTaskOut:
    """Преобразует ORM StudyTask в DTO, подтягивая services, эталон и схему доп. полей."""
    data = StudyTaskOut.model_validate(task).model_dump()
    data["services"] = [ServiceOut.model_validate(s) for s in task.services]
    if getattr(task, "etalon", None) is not None:
        data["etalon_content"] = task.etalon.content
        data["field_schema"] = task.etalon.field_schema
    if getattr(task, "extra_field_schemas", None):
        data["extra_field_schemas"] = [
            ExtraFieldSchemaOut.model_validate(x) for x in task.extra_field_schemas
        ]
    return StudyTaskOut(**data)