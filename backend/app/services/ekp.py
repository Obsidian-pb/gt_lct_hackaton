"""Единый классификатор происшествий (ЕКП).

Даёт детерминированный эталон: комбинация признаков однозначно задаёт итоговый
тип происшествия, а тип вместе с флагами опросной карты — список оповещаемых
служб. Благодаря этому заполнение карточки проверяется сверкой, а не оценкой LLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

# Служебное значение в ячейке: служба присутствует в классификаторе,
# но на это происшествие не реагирует.
NO_RESPONSE = "нет реагирования"


@dataclass(frozen=True)
class Notification:
    service: str
    incident_type_in_service: str
    variant: str | None
    variant_kind: str
    requires_flags: frozenset[str]

    @property
    def responds(self) -> bool:
        return self.incident_type_in_service.strip().lower() != NO_RESPONSE


@dataclass(frozen=True)
class Rule:
    number: int
    group: str
    signs: tuple[str, ...]
    incident_type: str
    incident_type_ekp35: str | None
    main_service: str | None
    hints: str | None
    notifications: tuple[Notification, ...]

    def resolve(self, flags: frozenset[str] | set[str] = frozenset()) -> dict[str, str]:
        """Список оповещения при заданных флагах опросной карты.

        У части служб несколько подколонок: одна по умолчанию и несколько под
        конкретные флаги. Если хоть один флаг службы взведён, подколонка по
        умолчанию не применяется.
        """
        flags = frozenset(flags)
        triggered: set[str] = {
            n.service
            for n in self.notifications
            if n.variant_kind == "flag" and n.requires_flags and n.requires_flags <= flags
        }

        result: dict[str, str] = {}
        for n in self.notifications:
            if n.variant_kind == "flag":
                if n.requires_flags:
                    if not n.requires_flags <= flags:
                        continue
                elif n.service in triggered:
                    continue
            if not n.responds:
                continue
            result.setdefault(n.service, n.incident_type_in_service)
        return result


class EKP:
    """Разобранный классификатор одной редакции.

    Строится из файла поставки, из байтов, сохранённых в базе вместе
    с загруженной редакцией, или из уже разобранного словаря — формат
    у всех трёх один, `data/ekp.json`.
    """

    def __init__(self, source: Path | bytes | dict) -> None:
        if isinstance(source, Path):
            raw = json.loads(source.read_text(encoding="utf-8"))
        elif isinstance(source, (bytes, bytearray)):
            raw = json.loads(source.decode("utf-8"))
        else:
            raw = source
        self.source: str = str(raw.get("source") or "")
        self.groups: tuple[str, ...] = tuple(raw["groups"])
        self.services: tuple[str, ...] = tuple(raw["services"])
        self._rules: dict[int, Rule] = {}
        for item in raw["rules"]:
            rule = Rule(
                number=item["number"],
                group=item["group"],
                signs=tuple(s for s in item["signs"] if s),
                incident_type=item["incident_type"] or "",
                incident_type_ekp35=item["incident_type_ekp35"],
                main_service=item["main_service"],
                hints=item["hints"],
                notifications=tuple(
                    Notification(
                        service=n["service"],
                        incident_type_in_service=n["incident_type_in_service"],
                        variant=n["variant"],
                        variant_kind=n["variant_kind"],
                        requires_flags=frozenset(n["requires_flags"]),
                    )
                    for n in item["notifications"]
                ),
            )
            self._rules[rule.number] = rule

    def __len__(self) -> int:
        return len(self._rules)

    def rule(self, number: int) -> Rule:
        return self._rules[number]

    def all_rules(self) -> tuple[Rule, ...]:
        return tuple(self._rules.values())

    def by_group(self, group: str) -> tuple[Rule, ...]:
        return tuple(r for r in self._rules.values() if r.group == group)

    def services_for(self, service: str) -> tuple[Rule, ...]:
        """Правила, по которым карточка может прийти указанной службе."""
        return tuple(
            r for r in self._rules.values() if any(n.service == service for n in r.notifications)
        )


@lru_cache
def get_ekp() -> EKP:
    """Встроенная редакция — из файла поставки.

    Это редакция всех занятий, у которых редакция не указана, и запасной
    вариант, когда администратор не включил ни одной загруженной. Редакции,
    загруженные через интерфейс, выдаёт `services.classifier_versions`.
    """
    return EKP(get_settings().ekp_path)
