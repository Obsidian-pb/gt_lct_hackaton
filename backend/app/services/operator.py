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

from app.models.training import CallOutcome
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
    # Что обучающийся решил сделать с обращением. Прежние вызовы приходят
    # без исхода — для них подразумевается классификация, как было раньше.
    outcome: CallOutcome = CallOutcome.CLASSIFY
    referral_target: str = ""


@dataclass(frozen=True)
class Expected:
    """Эталон обращения: что с ним следовало сделать."""

    outcome: CallOutcome
    rule_number: int | None = None
    referral_target: str | None = None


@dataclass
class OperatorAssessment:
    classification: ClassificationResult | None
    outcome_correct: bool = True
    # Требовалось ли вообще классифицировать происшествие: при передаче
    # по принадлежности и при отказе в регистрации опросная карта не нужна.
    classification_required: bool = True
    violations: list[Violation] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    deadline_seconds: int = DEFAULT_CALL_DEADLINE_SECONDS

    @property
    def score(self) -> float:
        """Балл складывается из классификации и оформления карточки.

        Классификация весит больше остального: от неё зависит, кто поедет
        на происшествие.
        """
        # Неверный исход обесценивает остальное: карточка, заведённая
        # на чужой регион, аккуратна и подробна, но бесполезна — силы
        # реагирования о происшествии не узнают.
        if not self.outcome_correct:
            return 0.0

        classification_score = self.classification.score if self.classification else 0.0
        penalty = sum(
            SEVERITY_PENALTY[v.kind.severity]
            for v in self.violations
            if v.code in {"O5", "O6", "O9"}
        )
        paperwork = max(0.0, 1.0 - penalty / 2.0)
        overdue = 1.0 if self.elapsed_seconds > self.deadline_seconds else 0.0
        # Там, где классифицировать не требовалось, весь балл держится
        # на оформлении: адрес и описание нужны и для передачи вызова.
        if self.classification is None and not self.classification_required:
            total = paperwork - 0.1 * overdue
        else:
            total = 0.7 * classification_score + 0.3 * paperwork - 0.1 * overdue
        return round(max(0.0, min(1.0, total)), 3)


def evaluate(
    card: FilledCard, expected: Expected | int, deadline_seconds: int
) -> OperatorAssessment:
    """Оценивает приём вызова.

    Вторым аргументом принимается эталон целиком; номер правила отдельным
    числом оставлен ради прежних вызовов, где исход всегда был один —
    классификация.
    """
    if isinstance(expected, int):
        expected = Expected(outcome=CallOutcome.CLASSIFY, rule_number=expected)

    result = OperatorAssessment(
        classification=None,
        elapsed_seconds=card.elapsed_seconds,
        deadline_seconds=deadline_seconds,
        classification_required=expected.outcome is CallOutcome.CLASSIFY,
    )

    _check_outcome(card, expected, result)

    # Опросную карту разбираем только там, где классификация и требовалась.
    # Признаки, выбранные к вызову из чужого региона, проверять не по чему:
    # правильного правила для него в московском классификаторе нет.
    if expected.outcome is CallOutcome.CLASSIFY and result.outcome_correct:
        if not card.group or not card.path:
            result.violations.append(
                Violation("O1", "Признаки происшествия не выбраны, карточка не классифицирована")
            )
        else:
            classification = classify(expected.rule_number, card.group, list(card.path))
            result.classification = classification
            _check_classification(classification, result)

    if not card.address.strip():
        result.violations.append(Violation("O5", "Адрес происшествия не внесён в карточку"))
    if not card.description.strip():
        result.violations.append(Violation("O6", "Описание происшествия не внесено"))

    # Превышение ориентира по времени снижает балл, но отдельным нарушением
    # не считается: разговор с заявителем может затянуться по его вине.
    return result


# Названия субъектов обучающийся пишет по-разному: «МО», «Московская обл.»,
# «Московская область». Сверять дословно значило бы штрафовать за форму
# записи, а не за существо, поэтому сравниваются ключевые слова.
REGION_ALIASES: dict[str, tuple[str, ...]] = {
    # «мо» здесь быть не должно: как подстрока оно находится внутри слова
    # «Москва», и столица засчиталась бы за область — то самое смешение,
    # которое вызов и проверяет. Сокращение опознаётся отдельным словом ниже.
    "московская область": ("московск", "подмосков"),
    "тульская область": ("тульск",),
    "рязанская область": ("рязан",),
    "владимирская область": ("владимирск",),
    "волгоградская область": ("волгоградск", "волжск"),
}


def _same_region(answer: str, expected: str) -> bool:
    """Совпадает ли названный субъект с эталонным."""
    answer = answer.strip().lower().replace("ё", "е")
    expected = expected.strip().lower().replace("ё", "е")
    if not answer:
        return False
    # Столица и область — разные субъекты, и путать их нельзя ни в какую
    # сторону, хотя названия схожи.
    if {answer, expected} == {"москва", "московская область"}:
        return False
    if expected in answer or answer in expected:
        return True
    for keys in REGION_ALIASES.get(expected, ()):
        if keys in answer:
            return True
    # «МО» как сокращение опознаётся только отдельным словом: иначе оно
    # нашлось бы внутри любого слова с этими буквами.
    return expected.startswith("московск") and answer in {"мо", "м.о.", "м/о"}


def _check_outcome(card: FilledCard, expected: Expected, result: OperatorAssessment) -> None:
    """Сверяет решение обучающегося о судьбе обращения с эталонным.

    Это первое, что оператор обязан понять: наше ли это происшествие
    и происшествие ли вообще. Ошибка здесь дороже ошибки в признаках —
    при ней вызов целиком уходит не туда или не уходит никуда.
    """
    if card.outcome is expected.outcome:
        if expected.outcome is CallOutcome.REFER and not card.referral_target.strip():
            result.violations.append(
                Violation("O9", "Не указан субъект, которому передаётся вызов")
            )
        elif expected.outcome is CallOutcome.REFER and expected.referral_target:
            if not _same_region(card.referral_target, expected.referral_target):
                result.violations.append(
                    Violation(
                        "O9",
                        f"Вызов передан в «{card.referral_target.strip()}», "
                        f"адрес относится к «{expected.referral_target}»",
                        evidence=card.referral_target.strip(),
                    )
                )
        return

    result.outcome_correct = False

    if expected.outcome is CallOutcome.REFER:
        where = expected.referral_target or "другой субъект"
        if card.outcome is CallOutcome.CLASSIFY:
            result.violations.append(
                Violation(
                    "O7",
                    f"Происшествие зарегистрировано как московское, "
                    f"адрес относится к «{where}» — вызов следовало передать "
                    f"по принадлежности",
                    evidence=card.address.strip() or None,
                )
            )
        else:
            result.violations.append(
                Violation(
                    "O10",
                    "Происшествие не зарегистрировано и не передано: "
                    f"вызов следовало передать в «{where}»",
                )
            )
    elif expected.outcome is CallOutcome.REJECT:
        result.violations.append(
            Violation(
                "O10",
                "Обращение не является происшествием для Системы-112, "
                "регистрировать его не следовало",
            )
        )
    else:
        # Эталон — классификация, а обучающийся от неё отказался.
        result.violations.append(
            Violation(
                "O8",
                "Происшествие в зоне ответственности Москвы "
                + (
                    "передано по принадлежности"
                    if card.outcome is CallOutcome.REFER
                    else "отклонено как не являющееся происшествием"
                ),
                evidence=card.address.strip() or None,
            )
        )


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
