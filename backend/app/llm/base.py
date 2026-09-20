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
    # Профильное ли происшествие для службы обучающегося. Определяет, будет
    # ли отказ от реагирования ошибкой, и должно согласовываться с эталонным
    # статусом: у непрофильного ожидается «Не принята».
    is_profile: bool = True
    # False, если модель не ответила: сценарий пустой и показывать его нельзя.
    available: bool = True

    @classmethod
    def unavailable(cls, incident_type: str) -> "GeneratedScenario":
        return cls(
            incident_description=incident_type,
            address="",
            caller="",
            signs=[],
            expected_primary_status="Принята",
            required_comment_points=[],
            available=False,
        )


class LLMProvider(Protocol):
    name: str

    async def probe(self) -> str:
        """Проверка связи: короткое обращение к модели.

        В отличие от остальных методов ошибку не глушит — администратору,
        который настраивает модель из интерфейса, нужна причина отказа.
        Возвращает имя ответившей модели.
        """
        ...

    async def review_comment(
        self, *, comment: str, required_points: list[str], context: str
    ) -> CommentReview: ...

    async def generate_scenario(
        self,
        *,
        incident_type: str,
        group: str,
        difficulty: str,
        service: str = ...,
        signs: list[str] | None = ...,
        note: str | None = ...,
    ) -> GeneratedScenario: ...
