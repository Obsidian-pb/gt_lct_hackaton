"""Провайдер без модели: лексическая проверка вместо смысловой.

Нужен, чтобы тренажёр и тесты работали при полностью отключённой LLM.
Качество оценки заведомо ниже: пункт считается раскрытым при совпадении
значимых слов, поэтому перефразированный ответ будет помечен как пропуск.
"""

from __future__ import annotations

import re

from app.llm.base import CommentReview, GeneratedScenario

STOPWORDS = frozenset(
    "и в во не на с со что а по к у за из о от для при об это как также был была было".split()
)


def _significant(text: str) -> set[str]:
    words = re.findall(r"\w{3,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


class StubProvider:
    name = "stub"

    async def review_comment(
        self, *, comment: str, required_points: list[str], context: str
    ) -> CommentReview:
        said = _significant(comment or "")
        missing = []
        for point in required_points:
            expected = _significant(point)
            if not expected:
                continue
            overlap = len(expected & said) / len(expected)
            if overlap < 0.5:
                missing.append(point)
        return CommentReview(
            missing_points=missing,
            summary="Смысловая проверка недоступна: сверка выполнена по ключевым словам.",
        )

    async def generate_scenario(
        self, *, incident_type: str, group: str, difficulty: str
    ) -> GeneratedScenario:
        return GeneratedScenario(
            incident_description=f"{incident_type} ({group}, сложность: {difficulty})",
            address="Москва",
            caller="Заявитель",
            signs=[],
            expected_primary_status="Принята",
            required_comment_points=[],
        )
