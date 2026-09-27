from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.catalog import Service

# --- Связующие таблицы -------------------------------------------------------

study_task_services = Table(
    "study_task_services",
    Base.metadata,
    Column(
        "study_task_id",
        ForeignKey("content.study_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        ForeignKey("catalog.services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="content",
)

scenario_tasks = Table(
    "scenario_tasks",
    Base.metadata,
    Column(
        "scenario_id",
        ForeignKey("content.scenarios.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "study_task_id",
        ForeignKey("content.study_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "sort_order",
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    ),
    schema="content",
)


class StudyTask(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    """Учебная задача (окно 8 ТЗ): диспозиция + классификация + эталон."""

    __tablename__ = "study_tasks"
    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        CheckConstraint(
            "status IN ('draft', 'review', 'approved', 'rejected', 'archived')",
            name="status_values",
        ),
        CheckConstraint(
            "jsonb_typeof(extra_fields) = 'object'", name="extra_fields_object"
        ),
        Index(
            "ix_study_tasks_lookup",
            "difficulty",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "content"},
    )

    # Сложность от 1 до 5 (ТЗ 8)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # Диспозиция: сообщение заявителя и телефоны
    caller_message: Mapped[str] = mapped_column(Text, nullable=False)
    aon_phone: Mapped[str | None] = mapped_column(String(32))
    provided_phone: Mapped[str | None] = mapped_column(String(32))
    scene_phone: Mapped[str | None] = mapped_column(String(32))

    # Заявитель
    caller_full_name: Mapped[str | None] = mapped_column(String(255))
    applicant_status_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reference.applicant_statuses.id", ondelete="SET NULL")
    )

    # Адрес (окно 33 ТЗ отдельно не делаем — адрес в составе задачи)
    country: Mapped[str | None] = mapped_column(String(128))
    federal_subject: Mapped[str | None] = mapped_column(String(255))
    locality: Mapped[str | None] = mapped_column(String(255))
    address_object: Mapped[str | None] = mapped_column(String(255))
    administrative_district: Mapped[str | None] = mapped_column(String(255))
    district: Mapped[str | None] = mapped_column(String(255))
    street: Mapped[str | None] = mapped_column(String(255))
    house: Mapped[str | None] = mapped_column(String(32))
    building: Mapped[str | None] = mapped_column(String(32))
    structure: Mapped[str | None] = mapped_column(String(32))
    apartment: Mapped[str | None] = mapped_column(String(32))
    entrance: Mapped[str | None] = mapped_column(String(32))
    floor: Mapped[str | None] = mapped_column(String(32))
    intercom_code: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    descriptive_address: Mapped[str | None] = mapped_column(Text)

    # Описание и признаки вызова
    incident_description: Mapped[str | None] = mapped_column(Text)
    has_victims: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    no_scene_refusal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    no_access: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    no_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    call_dropped: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Классификация происшествия: группа (код Г) и признаки 1-3 по компонентам.
    # Класс события (event_class_id) выводится из этих компонентов.
    event_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_types.id", ondelete="SET NULL")
    )
    event_feature_1_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_features_1.id", ondelete="SET NULL")
    )
    event_feature_2_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_features_2.id", ondelete="SET NULL")
    )
    event_feature_3_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_features_3.id", ondelete="SET NULL")
    )
    event_class_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.event_classes.id", ondelete="RESTRICT")
    )
    extra_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    # Службы
    main_service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.services.id", ondelete="SET NULL")
    )

    # Жизненный цикл и утверждение
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    services: Mapped[list[Service]] = relationship(
        secondary=study_task_services,
        lazy="selectin",
    )
    etalon: Mapped[TaskEtalon | None] = relationship(
        back_populates="study_task",
        cascade="all, delete-orphan",
        uselist=False,
        single_parent=True,
        lazy="selectin",
    )
    extra_field_schemas: Mapped[list[TaskExtraFieldSchema]] = relationship(
        back_populates="study_task",
        cascade="all, delete-orphan",
        order_by="TaskExtraFieldSchema.sort_order",
        lazy="selectin",
    )


class TaskEtalon(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Эталонная карточка учебной задачи (ТЗ 8): образец заполнения."""

    __tablename__ = "task_etalons"
    __table_args__ = (
        UniqueConstraint("study_task_id"),
        CheckConstraint("jsonb_typeof(content) = 'object'", name="content_object"),
        CheckConstraint("jsonb_typeof(field_schema) = 'array'", name="field_schema_array"),
        {"schema": "content"},
    )

    study_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.study_tasks.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    field_schema: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    study_task: Mapped[StudyTask] = relationship(back_populates="etalon")


class Scenario(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    """Учебный сценарий (окно 6 ТЗ): тема + набор учебных задач."""

    __tablename__ = "scenarios"
    __table_args__ = (
        Index(
            "ix_scenarios_lookup",
            "scenario_status_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "content"},
    )

    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scenario_status_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reference.scenario_statuses.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tasks: Mapped[list[StudyTask]] = relationship(
        secondary=scenario_tasks,
        lazy="selectin",
    )


class StudyMaterial(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    """Методический материал справочной базы (окно 18 ТЗ)."""

    __tablename__ = "study_materials"
    __table_args__ = {"schema": "content"}

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )


class TaskExtraFieldSchema(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Схема дополнительных полей учебной задачи.

    Определяет, какие дополнительные поля существуют у учебной задачи и
    её эталона/карточки (код, подпись, тип, обязательность, варианты).
    Значения этих полей хранятся отдельно:
      - учебная задача — study_tasks.extra_fields (JSONB);
      - карточка происшествия — incident_cards.content (JSONB).
    """

    __tablename__ = "task_extra_field_schemas"
    __table_args__ = (
        UniqueConstraint(
            "study_task_id",
            "code",
            name="uq_task_extra_field_schemas_study_task_code",
        ),
        CheckConstraint(
            "field_type IN ('text', 'number', 'boolean', 'select', 'date')",
            name="ck_task_extra_field_schemas_field_type_values",
        ),
        CheckConstraint(
            "jsonb_typeof(options) = 'array'",
            name="ck_task_extra_field_schemas_options_array",
        ),
        {"schema": "content"},
    )

    study_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.study_tasks.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(16), nullable=False)
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    options: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    study_task: Mapped[StudyTask] = relationship(back_populates="extra_field_schemas")