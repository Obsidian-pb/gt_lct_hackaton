"""Сопоставление экзаменационных вызовов с правилами классификатора.

Эталон в режиме оператора — номер правила ЕКП, поэтому ошибка здесь
обесценивает всю проверку. Полагаться на языковую модель вслепую нельзя:
из 1283 правил она уверенно назовёт несуществующее.

Поэтому порядок такой:
  1. поиск по значимым словам сужает классификатор до нескольких кандидатов;
  2. модель выбирает из этого списка и объясняет выбор;
  3. ответ принимается, только если номер есть среди кандидатов.

Итог всё равно попадает в систему неутверждённым: подтверждает преподаватель.
Это не перестраховка, а тот самый сценарий из технического задания.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.llm import get_llm_provider  # noqa: E402
from app.llm.openai_compatible import OpenAICompatibleProvider  # noqa: E402
from app.services.ekp import Rule, get_ekp  # noqa: E402

TICKETS = BACKEND_DIR / "data" / "tickets.json"
MATCHES = BACKEND_DIR / "data" / "ticket_rules.json"

# Слова вызова и слова классификатора нередко однокоренными не являются:
# заявитель говорит «дерутся», а в ЕКП записано «драка». Полноценная
# лемматизация тут избыточна, хватает словаря частых расхождений.
SYNONYMS = {
    "дерут": ["драка"],
    "дралис": ["драка"],
    "избит": ["избиение", "драка"],
    "горит": ["пожар", "возгорание"],
    "горят": ["пожар", "возгорание"],
    "возгор": ["пожар"],
    "задым": ["задымление", "дым"],
    "тонет": ["утонул", "вода"],
    "утону": ["утонул"],
    "сбила": ["наезд"],
    "сбил": ["наезд"],
    "угнал": ["угон"],
    "украл": ["кража"],
    "вскры": ["вскрывают", "кража"],
    "ножом": ["ранение", "нападение"],
    "повес": ["суицид"],
    "рожае": ["роды"],
    "задых": ["астма", "дыхание"],
    "заблуд": ["потерялся", "заблудился"],
    "потеря": ["потерялся"],
    "скончал": ["смерть", "труп"],
    "труп": ["смерть"],
    "запах": ["запах газа"],
    "прорыв": ["течь", "прорыв"],
    "затопи": ["течь", "залив"],
}

STOPWORDS = frozenset(
    "и в во не на с со что а по к у за из о от для при об это как также был была было "
    "вызывает заявитель звонит себе лет год года нет есть его ее их том там где".split()
)

SYSTEM_PROMPT = """\
Ты — специалист Службы 112 города Москвы. Оператор принял вызов и должен \
классифицировать происшествие по Единому классификатору.

Тебе дан текст вызова и пронумерованный список допустимых типов происшествия \
из классификатора. Выбери ОДИН, который точнее всего описывает происшествие.

Обращай внимание на различия, которые меняют классификацию: открытое пламя \
против дыма, наличие пострадавших, место происшествия (жилой дом, улица, \
транспорт, объект).

Если ни один вариант не подходит, верни number = 0.

Верни строго JSON:
{"number": <порядковый номер варианта из списка или 0>, "reason": "<одно предложение>"}"""


def significant(text: str) -> list[str]:
    words = re.findall(r"[а-яёА-ЯЁa-zA-Z]{4,}", text.lower())
    return [w for w in words if w not in STOPWORDS]


def candidates(situation: str, limit: int = 20) -> list[Rule]:
    """Правила классификатора, чьи признаки перекликаются с текстом вызова.

    Совпадение в самом типе происшествия весит больше, чем в признаках:
    у «задымления мусоропровода» слово «задымление» стоит именно в типе,
    и без такого веса наверх всплывали посторонние пожары.
    """
    words = significant(situation)
    if not words:
        return []

    scored: list[tuple[float, Rule]] = []
    for rule in get_ekp().all_rules():
        type_text = (rule.incident_type or "").lower()
        sign_text = " ".join(x for x in rule.signs if x).lower()
        group_text = (rule.group or "").lower()

        score = 0.0
        for word in words:
            stem = word[:5]
            variants = [stem, *SYNONYMS.get(stem, [])]
            if any(v in type_text for v in variants):
                score += 3.0
            elif any(v in sign_text for v in variants):
                score += 1.5
            elif any(v in group_text for v in variants):
                score += 0.5
        if score:
            scored.append((score, rule))

    scored.sort(key=lambda pair: (-pair[0], pair[1].number))
    return [rule for _, rule in scored[:limit]]


async def match_one(provider, situation: str) -> dict:
    options = candidates(situation)
    if not options:
        return {"rule_number": None, "reason": "кандидатов не найдено"}

    # Нумеруем позициями, а не номерами правил: восьмизначные числа модель
    # путает и возвращает то номер строки, то обрывок номера правила.
    listing = "\n".join(
        f"{i}. {r.incident_type} [{r.group}] — признаки: "
        + " / ".join(x for x in r.signs if x)
        for i, r in enumerate(options, start=1)
    )
    user = f"Вызов:\n{situation}\n\nДопустимые типы происшествия:\n{listing}"

    data = await provider._complete(SYSTEM_PROMPT, user)
    if data is None:
        return {"rule_number": None, "reason": "модель недоступна"}

    try:
        number = int(data.get("number") or 0)
    except (TypeError, ValueError):
        number = 0

    if number == 0:
        # Модель честно сказала, что подходящего варианта нет. Это лучше
        # уверенной ошибки: эталон с неверным типом учит неправильному.
        return {"rule_number": None, "reason": "подходящий тип не найден среди кандидатов"}
    if not 1 <= number <= len(options):
        return {"rule_number": None, "reason": f"выбрана позиция вне списка ({number})"}

    rule = options[number - 1]
    return {
        "rule_number": rule.number,
        "incident_type": rule.incident_type,
        "group": rule.group,
        "signs": [x for x in rule.signs if x],
        "reason": str(data.get("reason", ""))[:200],
    }


def load_done() -> dict[tuple[int, int], dict]:
    """Уже сопоставленные вызовы из предыдущего запуска.

    Один запрос к модели с размышлением занимает около минуты, а весь прогон —
    полчаса. Терять его из-за обрыва нельзя, поэтому результат копится на диске
    и повторный запуск продолжает с места остановки.
    """
    if not MATCHES.exists():
        return {}
    try:
        rows = json.loads(MATCHES.read_text(encoding="utf-8"))["matches"]
    except (json.JSONDecodeError, KeyError):
        return {}
    return {(r["ticket"], r["no"]): r for r in rows if r.get("rule_number")}


def save(rows: dict[tuple[int, int], dict]) -> None:
    ordered = [rows[key] for key in sorted(rows)]
    MATCHES.write_text(
        json.dumps(
            {"note": "Черновое сопоставление. Подтверждает преподаватель.", "matches": ordered},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


async def main(only_moscow: bool) -> None:
    payload = json.loads(TICKETS.read_text(encoding="utf-8"))
    provider = get_llm_provider()
    if not isinstance(provider, OpenAICompatibleProvider):
        print("Нужен провайдер с доступом к модели: задайте LLM_PROVIDER.", file=sys.stderr)
        raise SystemExit(1)

    results = load_done()
    if results:
        print(f"продолжаю: уже сопоставлено {len(results)}")
    limit = asyncio.Semaphore(3)
    write_lock = asyncio.Lock()

    async def process(ticket: int, call: dict) -> None:
        key = (ticket, call["no"])
        if key in results:
            return  # уже сопоставлено в прошлом запуске
        async with limit:
            row = {
                "ticket": ticket,
                "no": call["no"],
                "situation": call["situation"],
                "trap": call.get("trap"),
            }
            if only_moscow and call.get("trap"):
                # Вызов из другого региона передаётся по принадлежности,
                # а не классифицируется здесь.
                row.update(rule_number=None, reason="передача в другой регион")
            else:
                row.update(await match_one(provider, call["situation"]))
            results[key] = row
            # Пишем сразу: обрыв на середине не должен обесценивать прогон.
            async with write_lock:
                save(results)

    # return_exceptions: падение одного вызова не должно обрывать остальные
    # и обесценивать уже сделанное.
    outcomes = await asyncio.gather(
        *(
            process(t["ticket"], call)
            for t in payload["tickets"]
            for call in t["calls"]
        ),
        return_exceptions=True,
    )
    save(results)

    failed = [o for o in outcomes if isinstance(o, Exception)]
    matched = sum(1 for r in results.values() if r["rule_number"])
    print(f"сопоставлено {matched} из {len(results)}")
    if failed:
        print(f"сорвалось вызовов: {len(failed)} — повторный запуск их доберёт")
    print(f"записано: {MATCHES}")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Подбор правил ЕКП для вызовов из билетов")
    cli.add_argument(
        "--all",
        action="store_true",
        help="сопоставлять и вызовы из других регионов (по умолчанию пропускаются)",
    )
    asyncio.run(main(only_moscow=not cli.parse_args().all))
