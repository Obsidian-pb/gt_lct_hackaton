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
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    RetainedDeletionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# --- Связующие таблицы -------------------------------------------------------

classifier_version_events = Table(
    "classifier_version_events",
    Base.metadata,
    Column(
        "classifier_version_id",
        ForeignKey("catalog.classifier_versions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "event_class_id",
        ForeignKey("catalog.event_classes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    ),
    schema="catalog",
)

event_class_services = Table(
    "event_class_services",
    Base.metadata,
    Column(
        "event_class_id",
        ForeignKey("catalog.event_classes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "service_id",
        ForeignKey("catalog.services.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    schema="catalog",
)


class ClassifierVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Опубликованная версия классификатора происшествий."""

    __tablename__ = "classifier_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="version_number_positive"),
        Index(
            "uq_classifier_versions_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        {"schema": "catalog"},
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    published_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth.users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventType(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Верхний уровень классификатора — код «Г» (1..9)."""

    __tablename__ = "event_types"
    __table_args__ = (
        CheckConstraint("code BETWEEN 1 AND 9", name="code_range"),
        {"schema": "catalog"},
    )

    code: Mapped[int] = mapped_column(SmallInteger, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class EventFeature1(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Признак 1 происшествия."""

    __tablename__ = "event_features_1"
    __table_args__ = (
        UniqueConstraint("event_type_id", "code"),
        CheckConstraint("code BETWEEN 0 AND 99", name="code_range"),
        {"schema": "catalog"},
    )

    event_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_types.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    statistics_name: Mapped[str] = mapped_column(String(512), nullable=False)
    operator_label: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)


class EventFeature2(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Признак 2 происшествия."""

    __tablename__ = "event_features_2"
    __table_args__ = (
        UniqueConstraint("event_feature_1_id", "code"),
        CheckConstraint("code BETWEEN 0 AND 99", name="code_range"),
        {"schema": "catalog"},
    )

    event_feature_1_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_features_1.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class EventFeature3(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Признак 3 происшествия."""

    __tablename__ = "event_features_3"
    __table_args__ = (
        UniqueConstraint("event_feature_2_id", "code"),
        CheckConstraint("code BETWEEN 0 AND 99", name="code_range"),
        {"schema": "catalog"},
    )

    event_feature_2_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_features_2.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class EventClass(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    """Класс события — допустимая комбинация Группа + Признаки 1-3.

    Номер события формируется по формуле:
    Г × 1 000 000 + Признак1 × 10 000 + Признак2 × 100 + Признак3.
    """

    __tablename__ = "event_classes"
    __table_args__ = (
        UniqueConstraint(
            "event_type_id",
            "event_feature_1_id",
            "event_feature_2_id",
            "event_feature_3_id",
            name="uq_event_classes_components",
        ),
        Index("ix_event_classes_event_number", "event_number", unique=True),
        {"schema": "catalog"},
    )

    event_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_types.id", ondelete="RESTRICT"), nullable=False
    )
    event_feature_1_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_features_1.id", ondelete="RESTRICT"), nullable=False
    )
    event_feature_2_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_features_2.id", ondelete="RESTRICT"), nullable=False
    )
    event_feature_3_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_features_3.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    ekp35_type: Mapped[str | None] = mapped_column(String(512))
    scenario_code: Mapped[str | None] = mapped_column(String(64))
    main_service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("catalog.services.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Service(UUIDPrimaryKeyMixin, TimestampMixin, RetainedDeletionMixin, Base):
    """Справочник служб (окно 34 ТЗ): id, название, описание."""

    __tablename__ = "services"
    __table_args__ = {"schema": "catalog"}

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class EventClassExtraField(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Дополнительное поле группы происшествий (окно 29 ТЗ).

    Перечень полей, которые должны заполняться в карточке в зависимости
    от группы происшествий. Значения хранятся в JSONB-содержимом карточки.
    """

    __tablename__ = "event_class_extra_fields"
    __table_args__ = (
        UniqueConstraint("event_class_id", "code"),
        CheckConstraint(
            "field_type IN ('text', 'number', 'boolean', 'select', 'date')",
            name="field_type_values",
        ),
        CheckConstraint("jsonb_typeof(options) = 'array'", name="options_array"),
        {"schema": "catalog"},
    )

    event_class_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalog.event_classes.id", ondelete="CASCADE"), nullable=False
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