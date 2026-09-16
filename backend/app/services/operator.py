"""Приём вызова и заполнение карточки оператором Службы 112.

Оператор слушает заявителя, классифицирует происшествие по опросной карте
и регистрирует адрес с описанием. Итоговый тип и список оповещения
вычисляются классификатором, поэтому оценка здесь полностью детерминирована:
эталон — не мнение модели, а строка ЕКП.

Норматив времени отличается от диспетчерского: 30 секунд ПП РФ № 1931
относятся к подтверждению приёма карточки службой, а оператор всё это время
разговаривает с заявителем.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.survey import ClassificationResult, classify
from app.services.violations import Severity, Violation

# Ориентир на обработку одного вызова. Преподаватель может изменить.
DEFAULT_CALL_DEADLINE_SECONDS = 180

SEVERITY_PENALTY = {Severity.CRITICAL: 1.0, Severity.MAJOR: 0.5, Severity.MINOR: 0.25}


@dataclass(frozen=True)
class FilledCard:
    """Что обучающийся внёс в карточку."""

    group: str | None
    path: tuple[str, ...]
    address: str
    description: str
    elapsed_seconds: float


@dataclass
class OperatorAssessment:
    classification: ClassificationResult | None
    violations: list[Violation] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    deadline_seconds: int = DEFAULT_CALL_DEADLINE_SECONDS

    @property
    def score(self) -> float:
        """Балл складывается из классификации и оформления карточки.

        Классификация весит больше остального: от неё зависит, кто поедет
        на происшествие.
        """
        classification_score = self.classification.score if self.classification else 0.0
        penalty = sum(
            SEVERITY_PENALTY[v.kind.severity]
            for v in self.violations
            if v.code in {"O5", "O6"}
        )
        paperwork = max(0.0, 1.0 - penalty / 2.0)
        overdue = 1.0 if self.elapsed_seconds > self.deadline_seconds else 0.0
        total = 0.7 * classification_score + 0.3 * paperwork - 0.1 * overdue
        return round(max(0.0, min(1.0, total)), 3)


def evaluate(
    card: FilledCard, expected_rule_number: int, deadline_seconds: int
) -> OperatorAssessment:
    result = OperatorAssessment(
        classification=None,
        elapsed_seconds=card.elapsed_seconds,
        deadline_seconds=deadline_seconds,
    )

    if not card.group or not card.path:
        result.violations.append(
            Violation("O1", "Признаки происшествия не выбраны, карточка не классифицирована")
        )
    else:
        classification = classify(expected_rule_number, card.group, list(card.path))
        result.classification = classification
        _check_classification(classification, result)

    if not card.address.strip():
        result.violations.append(Violation("O5", "Адрес происшествия не внесён в карточку"))
    if not card.description.strip():
        result.violations.append(Violation("O6", "Описание происшествия не внесено"))

    # Превышение ориентира по времени снижает балл, но отдельным нарушением
    # не считается: разговор с заявителем может затянуться по его вине.
    return result


def _check_classification(
    classification: ClassificationResult, result: OperatorAssessment
) -> None:
    if classification.correct:
        return

    expected = classification.expected_rule
    if classification.chosen_rule is None:
        result.violations.append(
            Violation(
                "O1",
                "Выбор признаков не доведён до итогового типа происшествия",
                evidence=f"следовало: {expected.incident_type}",
            )
        )
    elif not classification.same_group:
        result.violations.append(
            Violation(
                "O2",
                f"Выбрана группа «{classification.chosen_rule.group}», "
                f"следовало «{expected.group}»",
                evidence=classification.chosen_rule.incident_type,
            )
        )
    else:
        result.violations.append(
            Violation(
                "O3",
                f"Зарегистрирован тип «{classification.chosen_rule.incident_type}», "
                f"следовало «{expected.incident_type}»",
                evidence=classification.chosen_rule.incident_type,
            )
        )

    if classification.missed_services:
        listed = ", ".join(classification.missed_services[:6])
        more = len(classification.missed_services) - 6
        result.violations.append(
            Violation(
                "O4",
                f"Из-за ошибки в классификации не были бы оповещены: {listed}"
                + (f" и ещё {more}" if more > 0 else ""),
                evidence=f"{len(classification.missed_services)} служб",
            )
        )
