"""Опросная карта оператора Службы 112.

Оператор классифицирует происшествие, последовательно выбирая формализованные
признаки. Каждая комбинация признаков однозначно задаёт итоговый тип
происшествия, а он — список оповещаемых служб. Дерево признаков строится
из того же классификатора, что и всё остальное.

Ошибка в классификации важна не сама по себе: из-за неё на происшествие
не поедет нужная служба. Поэтому разбор показывает не только неверный тип,
но и кого забыли оповестить.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from app.services.ekp import Rule, get_ekp


@dataclass
class SurveyNode:
    """Узел опросной карты: признак и то, что можно выбрать следом."""

    label: str
    children: dict[str, "SurveyNode"] = field(default_factory=dict)
    # Заполнен, если выбор признаков на этом узле уже завершён.
    rule_number: int | None = None
    incident_type: str | None = None

    @property
    def is_final(self) -> bool:
        return self.rule_number is not None


# Пометка в классификаторе для правил, которые оператор Службы 112 не выбирает:
# такие карточки приходят из внешних информационных систем.
HIDDEN_FROM_OPERATOR = "Не отображается оператору 112"


@lru_cache
def survey_tree() -> dict[str, SurveyNode]:
    """Дерево признаков по группам происшествий."""
    roots: dict[str, SurveyNode] = {}
    for rule in get_ekp().all_rules():
        signs = [s for s in rule.signs if s]
        if not signs or signs[0] == HIDDEN_FROM_OPERATOR:
            continue
        node = roots.setdefault(rule.group, SurveyNode(label=rule.group))
        for sign in signs:
            node = node.children.setdefault(sign, SurveyNode(label=sign))
        # Более общее правило может оказаться префиксом более частного;
        # тип закрепляем за тем узлом, на котором признаки закончились.
        node.rule_number = rule.number
        node.incident_type = rule.incident_type
    return roots


def options_at(group: str, path: list[str]) -> list[dict]:
    """Что оператор может выбрать на текущем шаге."""
    roots = survey_tree()
    node = roots.get(group)
    if node is None:
        return []
    for sign in path:
        node = node.children.get(sign)
        if node is None:
            return []
    return [
        {
            "label": label,
            "has_children": bool(child.children),
            "is_final": child.is_final,
            "incident_type": child.incident_type,
        }
        for label, child in node.children.items()
    ]


def resolve(group: str, path: list[str]) -> Rule | None:
    """Правило, к которому привёл выбранный путь признаков."""
    node = survey_tree().get(group)
    if node is None:
        return None
    for sign in path:
        node = node.children.get(sign)
        if node is None:
            return None
    if node.rule_number is None:
        return None
    return get_ekp().rule(node.rule_number)


@dataclass(frozen=True)
class ClassificationResult:
    correct: bool
    chosen_rule: Rule | None
    expected_rule: Rule
    # Сколько признаков подряд совпало с эталоном.
    matched_depth: int
    expected_depth: int
    # Службы, которые не были бы оповещены из-за ошибки, и лишние.
    missed_services: tuple[str, ...]
    extra_services: tuple[str, ...]

    @property
    def same_group(self) -> bool:
        return self.chosen_rule is not None and self.chosen_rule.group == self.expected_rule.group

    @property
    def score(self) -> float:
        """Доля за классификацию.

        Полный балл — только за точное совпадение типа. Частичный — за верно
        начатый путь: оператор, выбравший «жилой дом / лифт» вместо
        «жилой дом / лифт / открытое пламя», ошибся куда меньше того,
        кто ушёл в другую группу.
        """
        if self.correct:
            return 1.0
        if not self.same_group:
            return 0.0
        return round(0.6 * self.matched_depth / max(self.expected_depth, 1), 3)


def classify(
    expected_rule_number: int, group: str, path: list[str]
) -> ClassificationResult:
    ekp = get_ekp()
    expected = ekp.rule(expected_rule_number)
    chosen = resolve(group, path)

    expected_signs = [s for s in expected.signs if s]
    matched = 0
    if group == expected.group:
        for chosen_sign, expected_sign in zip(path, expected_signs):
            if chosen_sign != expected_sign:
                break
            matched += 1

    expected_services = set(expected.resolve())
    chosen_services = set(chosen.resolve()) if chosen else set()
    return ClassificationResult(
        correct=chosen is not None and chosen.number == expected.number,
        chosen_rule=chosen,
        expected_rule=expected,
        matched_depth=matched,
        expected_depth=len(expected_signs),
        missed_services=tuple(sorted(expected_services - chosen_services)),
        extra_services=tuple(sorted(chosen_services - expected_services)),
    )
