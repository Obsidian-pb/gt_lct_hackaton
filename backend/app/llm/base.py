"""Контракт провайдера ИИ-оценки.

Провайдер подменяется настройкой llm_provider без изменения кода приложения:
внешний API на демонстрации, локальная модель в изолированном контуре.
Любая оценка, которую даёт LLM, — дополнение к детерминированной проверке,
а не замена: при недоступности провайдера система продолжает работать.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class CommentReview:
    """Результат смысловой проверки комментария к статусу реагирования."""

    missing_points: list[str] = field(default_factory=list)
    grammar_issues: list[str] = field(default_factory=list)
    summary: str = ""
    # False, если провайдер недоступен: оценка выставлена без участия LLM.
    available: bool = True


@dataclass(frozen=True)
class GeneratedScenario:
    incident_description: str
    address: str
    caller: str
    signs: list[str]
    expected_primary_status: str
    required_comment_points: list[str]


class LLMProvider(Protocol):
    name: str

    async def review_comment(
        self, *, comment: str, required_points: list[str], context: str
    ) -> CommentReview: ...

    async def generate_scenario(
        self, *, incident_type: str, group: str, difficulty: str
    ) -> GeneratedScenario: ...
