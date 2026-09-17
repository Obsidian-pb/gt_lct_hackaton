"""Сравнение языковых моделей на проверке комментария диспетчера.

Модель в этом решении не выставляет балл: нарушения и оценку считает
классификатор и конечный автомат статусов. За моделью — смысловая проверка
комментария к статусу реагирования, и здесь у неё две возможные ошибки
разной цены:

* ложное замечание — пункт раскрыт, а модель говорит, что нет. Обучающийся
  получает несправедливый упрёк и перестаёт доверять разбору;
* пропуск — пункт не раскрыт, а модель его засчитала. Обучающийся не узнаёт
  о своей ошибке.

Первая ошибка хуже: неверный упрёк подрывает доверие ко всему тренажёру.
Поэтому они считаются отдельно, а не сводятся в одну «точность».

Примеры построены на карточках из памятки ГБУ «Система 112» — те же, что
в scripts/seed.py. Для каждого известно, какие обязательные пункты комментарий
раскрывает, поэтому эталон здесь задан человеком, а не другой моделью.

Запуск:
    python scripts/compare_llm.py                 # провайдер из настроек
    python scripts/compare_llm.py --alt           # ещё и альтернативный
                                                  # профиль из ALT_LLM_*
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.llm import get_llm_provider  # noqa: E402
from app.llm.base import LLMProvider  # noqa: E402
from app.llm.openai_compatible import OpenAICompatibleProvider  # noqa: E402

LIFT = "Застревание в лифте между 5 и 6 этажом, два человека, помощь не требуется"
ALARM = "Сработала пожарная сигнализация в жилом доме, признаков возгорания нет"
WIRE = "Во дворе жилого дома оборван провод, висит на высоте около двух метров"
PIPE = "Прорыв трубы с горячей водой в подвале жилого дома, заливает подъезд"
BASEMENT = "В подвале жилого дома находятся посторонние граждане"

LIFT_POINTS = [
    "лифты в доме обслуживает другая организация",
    "информация передана в диспетчерскую «Практика»",
]
ALARM_POINTS = [
    "дом обслуживает управляющая компания «ПИК»",
    "информация передана в диспетчерскую управляющей компании",
]
WIRE_POINTS = ["провод принадлежит «Ростелеком»", "информация передана по принадлежности"]
PIPE_POINTS = ["работы ведёт аварийная бригада", "на месте главный инженер"]
BASEMENT_POINTS = ["принято к реагированию"]


@dataclass(frozen=True)
class Case:
    context: str
    points: list[str]
    comment: str
    # Номера пунктов (с нуля), которые комментарий НЕ раскрывает.
    missing: set[int] = field(default_factory=set)
    # Ожидается ли замечание к грамматике. None — не проверяем.
    grammar: bool | None = None


# Пункты раскрыты своими словами: дословного совпадения от обучающегося
# не требуется, и модель обязана это понимать.
CASES = [
    Case(LIFT, LIFT_POINTS,
         "Лифтовое оборудование в доме обслуживает ООО «Практика», "
         "информация передана в их диспетчерскую.", set(), grammar=False),
    Case(LIFT, LIFT_POINTS, "Не обслуживаем.", {0, 1}),
    Case(LIFT, LIFT_POINTS, "Лифты в доме обслуживает сторонняя организация.", {1}),
    Case(ALARM, ALARM_POINTS,
         "Дом находится на обслуживании управляющей компании «ПИК», сведения "
         "переданы её дежурному диспетчеру.", set(), grammar=False),
    Case(ALARM, ALARM_POINTS,
         "Информация передана в диспетчерскую управляющей компании.", {0}),
    Case(ALARM, ALARM_POINTS, "Сигнализация сработала ложно, выезд не требуется.", {0, 1}),
    Case(WIRE, WIRE_POINTS,
         "Провод принадлежит «Ростелеком», информация передана по принадлежности.",
         set(), grammar=False),
    Case(WIRE, WIRE_POINTS, "Провод принадлежит «Ростелеком».", {1}),
    Case(PIPE, PIPE_POINTS,
         "На месте работает аварийная бригада, работами руководит главный инженер.",
         set(), grammar=False),
    Case(PIPE, PIPE_POINTS, "Работы ведёт аварийная бригада.", {1}),
    Case(BASEMENT, BASEMENT_POINTS, "Принято к реагированию, наряд направлен.", set()),
    Case(BASEMENT, BASEMENT_POINTS, "", {0}),
    # Орфография: пункт раскрыт, но в слове ошибка. Замечание к грамматике
    # не должно превращаться в замечание по существу.
    Case(PIPE, ["работы ведёт аварийная бригада"],
         "Аварийная бригада прибыла на место, течь локализованна.",
         set(), grammar=True),
    Case(ALARM, ["информация передана в диспетчерскую управляющей компании"],
         "Информация передана в диспетчерскую упровляющей компании.",
         set(), grammar=True),
    Case(BASEMENT, BASEMENT_POINTS,
         "Принято к реагированию, наряд направлен на адресс.", set(), grammar=True),
]


@dataclass
class Tally:
    exact: int = 0          # состав «не раскрыто» совпал полностью
    false_alarms: int = 0   # пункт раскрыт, а назван нераскрытым
    misses: int = 0         # пункт не раскрыт, а засчитан
    grammar_hit: int = 0
    grammar_total: int = 0
    grammar_false: int = 0
    failures: int = 0       # провайдер не ответил
    seconds: float = 0.0


async def run(provider: LLMProvider, label: str) -> Tally:
    tally = Tally()
    print(f"\n=== {label} ===")
    for number, case in enumerate(CASES, 1):
        started = time.monotonic()
        review = await provider.review_comment(
            comment=case.comment, required_points=case.points, context=case.context
        )
        tally.seconds += time.monotonic() - started
        if not review.available:
            tally.failures += 1
            print(f"{number:2}. провайдер недоступен")
            continue

        got = {case.points.index(p) for p in review.missing_points if p in case.points}
        false_alarms = got - case.missing
        misses = case.missing - got
        tally.false_alarms += len(false_alarms)
        tally.misses += len(misses)
        ok = not false_alarms and not misses
        tally.exact += ok

        note = "верно" if ok else ""
        if false_alarms:
            note = "ЛОЖНОЕ ЗАМЕЧАНИЕ: " + "; ".join(case.points[i] for i in false_alarms)
        if misses:
            note = (note + " | " if note else "") + "ПРОПУСК: " + "; ".join(
                case.points[i] for i in misses
            )

        if case.grammar is not None:
            tally.grammar_total += case.grammar
            found = bool(review.grammar_issues)
            if case.grammar and found:
                tally.grammar_hit += 1
            if not case.grammar and found:
                tally.grammar_false += 1
                note += f" | грамматика на ровном месте: {review.grammar_issues}"
            if case.grammar and not found:
                note += " | орфографическую ошибку не заметил"

        print(f"{number:2}. {note}")
    return tally


def report(label: str, tally: Tally) -> None:
    total = len(CASES)
    print(f"\n{label}")
    print(f"  состав «не раскрыто» точен: {tally.exact} из {total}")
    print(f"  ложных замечаний:           {tally.false_alarms}")
    print(f"  пропущенных пунктов:        {tally.misses}")
    print(
        f"  орфография найдена:         {tally.grammar_hit} из {tally.grammar_total}"
        f" (на чистых текстах придумал: {tally.grammar_false})"
    )
    if tally.failures:
        print(f"  не ответил:                 {tally.failures}")
    print(f"  среднее время ответа:       {tally.seconds / total:.1f} с")


def alt_provider() -> tuple[LLMProvider, str] | None:
    """Профиль для сравнения: модель в локальной сети или другой внешний API."""
    base_url = os.environ.get("ALT_LLM_BASE_URL")
    if not base_url:
        return None
    model = os.environ.get("ALT_LLM_MODEL", "")
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        api_key=os.environ.get("ALT_LLM_API_KEY", ""),
        model=model,
        timeout=float(os.environ.get("ALT_LLM_TIMEOUT_SECONDS", "180")),
        name="alt",
        disable_thinking=os.environ.get("ALT_LLM_DISABLE_THINKING", "") == "true",
    )
    return provider, f"{model} ({base_url})"


async def main(with_alt: bool) -> None:
    settings = get_settings()
    results = [(settings.llm_provider, await run(get_llm_provider(), settings.llm_provider))]

    if with_alt:
        alt = alt_provider()
        if alt is None:
            print("\nALT_LLM_BASE_URL не задан — сравнивать не с чем.", file=sys.stderr)
        else:
            provider, label = alt
            results.append((label, await run(provider, label)))

    print("\n" + "=" * 60)
    for label, tally in results:
        report(label, tally)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Сравнение моделей на проверке комментария")
    cli.add_argument("--alt", action="store_true", help="сравнить с профилем ALT_LLM_*")
    asyncio.run(main(cli.parse_args().alt))
