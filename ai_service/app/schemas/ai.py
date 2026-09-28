"""Pydantic-контракт stateless REST-операций ИИ-микросервиса.

Микросервис не хранит состояние: снимки карточки, классификации и истории
диалога передаются в теле запроса, ответы повторяют структуры функций ядра.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    service: str
    version: str


class AIStatusOut(BaseModel):
    state: str
    message: str
    provider: str | None = None
    model: str | None = None
    model_selected: bool = False
    scope_detected: bool = False


class CardGenerationIn(BaseModel):
    """Запрос генерации содержимого карточки (card_factory.generate)."""

    topic: str = Field(..., max_length=3000)
    category: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=160)
    flags: dict[str, str] | None = None
    index: int = Field(default=1, ge=1, le=100)
    total: int = Field(default=1, ge=1, le=100)
    recent_titles: list[str] | None = None
    classification: dict[str, Any] | None = None
    incident_class: dict[str, Any] | None = None


class ReferencePreviewIn(BaseModel):
    """Запрос превью эталона (card_reference.generate)."""

    content: dict[str, Any]
    caller_scenario: dict[str, Any] | None = None
    incident_class: dict[str, Any] | None = None


class CallerReplyIn(BaseModel):
    """Запрос реплики заявителя (card_caller.ask)."""

    content: dict[str, Any]
    caller_scenario: dict[str, Any]
    question: str = Field(..., min_length=1, max_length=2000)
    turns: list[dict[str, Any]] = Field(default_factory=list)
    level: str | None = Field(default=None, pattern="^(easy|medium|hard)$")


class ServiceReplyIn(BaseModel):
    """Запрос реплики службы ДДС (dds.service_reply)."""

    service: dict[str, Any] = Field(default_factory=dict)
    persona: str = Field(default="сотрудник учебной службы", max_length=2000)
    level: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    history: list[dict[str, Any]] = Field(default_factory=list)
    question: str = Field(..., min_length=1, max_length=2000)
    mode: str = Field(default="clear", pattern="^(clear|partial|drop|hangup)$")
    attempt: int = Field(default=1, ge=1, le=100)


class ValidateFieldsIn(BaseModel):
    """Запрос локальной валидации содержимого карточки."""

    content: dict[str, Any]


class AssessIn(BaseModel):
    """Запрос предварительной оценки ИИ (ai_core.assess_card)."""

    labels: dict[str, str]
    card: dict[str, Any]
    expected: dict[str, Any]
    history: list[dict[str, Any]] = Field(default_factory=list)
    hints_used: int = Field(default=0, ge=0, le=100)