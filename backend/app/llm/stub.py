"""Режим без языковой модели.

Смысловую проверку комментариев выполнить нечем, поэтому провайдер честно
сообщает, что она не выполнена, и не выставляет нарушений.

Сверку по ключевым словам здесь пробовали и убрали: она штрафовала за верный
ответ, изложенный своими словами. Например, комментарий «кабель относится
к Ростелекому, сведения направлены им по принадлежности» раскрывает оба
обязательных пункта, но по словам не совпадает ни с одним. Ложное обвинение
обучающегося хуже отсутствия проверки, а детерминированная часть оценки —
норматив, статусы, последовательность, обязательность комментариев —
работает и без модели.
"""

from __future__ import annotations

from app.llm.base import CommentReview, GeneratedScenario


class StubProvider:
    name = "stub"

    async def review_comment(
        self, *, comment: str, required_points: list[str], context: str
    ) -> CommentReview:
        return CommentReview(available=False)

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
