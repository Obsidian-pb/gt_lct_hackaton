from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AIGenerateIn(BaseModel):
    """Запрос генерации содержимого учебной задачи ИИ."""

    topic: str | None = Field(default=None, max_length=3000)
    location: str | None = Field(default=None, max_length=160)
    flags: dict[str, str] | None = None
    index: int = Field(default=1, ge=1, le=100)
    total: int = Field(default=1, ge=1, le=100)


class AIStatusOut(BaseModel):
    state: str
    message: str
    provider: str | None = None
    model: str | None = None
    model_selected: bool = False
    scope_detected: bool = False


class ReferencePreviewIn(BaseModel):
    caller_scenario_phone: str | None = Field(default=None, max_length=64)


class CallerReplyIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    turns: list[dict[str, Any]] = Field(default_factory=list)
    level: str | None = Field(default=None, pattern="^(easy|medium|hard)$")


class ServicePersonaIn(BaseModel):
    name: str = Field(default="Учебная служба", max_length=255)
    role: str = Field(default="диспетчер службы", max_length=255)
    knowledge: str = Field(
        default="Знает только свою должность и компетенцию. О происшествии узнаёт из звонка диспетчера ДДС.",
        max_length=4000,
    )


class ServiceReplyIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, Any]] = Field(default_factory=list)
    mode: str = Field(default="clear", pattern="^(clear|partial|drop|hangup)$")
    attempt: int = Field(default=1, ge=1, le=100)
    service: ServicePersonaIn | None = None
    persona: str | None = Field(default=None, max_length=2000)
    level: str | None = Field(default=None, pattern="^(easy|medium|hard)$")


class AIEvalIn(BaseModel):
    history: list[dict[str, Any]] = Field(default_factory=list)
    hints_used: int = Field(default=0, ge=0, le=100)


class CallerReplyOut(BaseModel):
    reply: str
    callback_disclosed: bool = False
    prompt_version: str | None = None


class ServiceReplyOut(BaseModel):
    reply: str
    delivered: str
    mode: str


class ReferencePreviewOut(BaseModel):
    task_id: UUID
    etalon_content: dict[str, Any]
    field_schema: list[Any]
    reference: dict[str, Any]


class ValidateFieldsIn(BaseModel):
    content: dict[str, Any]


class ValidateFieldsOut(BaseModel):
    valid: bool
    content: dict[str, Any]
