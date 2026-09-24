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
class Reason:
    """Почему служба есть в списке оповещения — или почему её там нет.

    Список сам по себе учит мало: обучающийся видит «МВД, СМП, ЦЭМП» и не
    понимает, откуда взялась скорая. Обоснование связывает службу с признаком
    опросной карты: «СМП — потому что отмечены пострадавшие», «МОСГАЗ — только
    при признаке газификации, здесь не отмечен». Это и есть то, что оператор
    должен усвоить: список выводится из признаков, а не запоминается.
    """

    service: str
    incident_type_in_service: str
    # always — служба оповещается при этом типе всегда; flag — её добавил
    # отмеченный признак; conditional — оповещалась бы при признаке, которого
    # в этом вызове нет.
    kind: str
    flags: tuple[str, ...]
    notified: bool

    @property
    def text(self) -> str:
        titles = [f"«{f.replace('_', ' ')}»" for f in self.flags]
        if self.kind == "always":
            return "оповещается при этом типе происшествия всегда"
        if self.kind == "flag":
            return "потому что отмечен признак " + " и ".join(titles)
        return "только при признаке " + " или ".join(titles) + " — в этом вызове не отмечен"


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

    def explain(self, flags: frozenset[str] | set[str] = frozenset()) -> tuple[Reason, ...]:
        """Список оповещения с обоснованием по каждой службе.

        Сначала оповещённые в порядке классификатора, затем те, кого добавил
        бы признак: их тоже стоит показать — именно они и есть урок.
        """
        flags = frozenset(flags)
        notified = self.resolve(flags)
        reasons: list[Reason] = []
        seen: set[str] = set()
        for n in self.notifications:
            if n.service in seen or n.service not in notified:
                continue
            seen.add(n.service)
            triggered = sorted(
                f
                for m in self.notifications
                if m.service == n.service
                and m.variant_kind == "flag"
                and m.requires_flags
                and m.requires_flags <= flags
                and m.responds
                for f in m.requires_flags
            )
            reasons.append(
                Reason(
                    service=n.service,
                    incident_type_in_service=notified[n.service],
                    kind="flag" if triggered else "always",
                    flags=tuple(triggered),
                    notified=True,
                )
            )
        for n in self.notifications:
            if n.service in seen:
                continue
            # Признаки, любой из которых добавил бы службу. Подколонки
            # с «нет реагирования» не считаются: они службу не добавляют.
            options = sorted(
                {
                    f
                    for m in self.notifications
                    if m.service == n.service and m.requires_flags and m.responds
                    for f in m.requires_flags
                }
            )
            if not options:
                continue
            seen.add(n.service)
            reasons.append(
                Reason(
                    service=n.service,
                    incident_type_in_service=n.incident_type_in_service,
                    kind="conditional",
                    flags=tuple(options),
                    notified=False,
                )
            )
        return tuple(reasons)

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
