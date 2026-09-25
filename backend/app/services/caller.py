"""Заявитель на линии: оператор задаёт вопросы, модель отвечает за заявителя.

Запись вызова — монолог, а работа оператора — диалог: «какой подъезд?»,
«пострадавшие есть?». Умение задать нужный вопрос и есть то, чему учим.
Модель знает только обстоятельства сценария и на остальное отвечает
«не знаю»; без модели заявитель молчит — сочинять за него нельзя.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.base import CallerReply, LLMProvider
from app.models.base import utcnow
from app.models.training import Attempt, CallerRole, Scenario

# Восемь вопросов — с запасом: в настоящем разговоре оператор уточняет три-пять
# вещей, а бесконечный диалог превращает тренажёр в чат.
MAX_TURNS = 8

ROLE_TEXT = {
    CallerRole.PARTICIPANT: "ты участник происшествия, оно случилось с тобой",
    CallerRole.WITNESS: "ты очевидец, видишь происходящее со стороны",
    CallerRole.RELATIVE: "ты родственник, знаешь о происшествии с чужих слов и не на месте",
}
DIFFICULTY_TEXT = {1: "низкая", 2: "средняя", 3: "высокая"}
FLAG_FACTS = {
    "пострадавшие": "есть пострадавшие",
    "пострадавшие_не_на_месте": "пострадавшие уже уехали или отказались от скорой",
    "нет_доступа": "в помещение не попасть, люди заблокированы",
    "угроза_людям": "есть угроза людям",
    "газификация": "дом газифицирован",
    "правонарушение": "это правонарушение",
}


@dataclass(frozen=True)
class Turn:
    question: str
    answer: str
    at: str


def facts_for(scenario: Scenario) -> str:
    """Что заявитель знает. Только сценарий — ни типа по классификатору, ни служб."""
    lines = [f"- Что случилось: {scenario.description.strip()}"]
    if scenario.address:
        lines.append(f"- Где: {scenario.address.strip()}")
    if scenario.caller:
        lines.append(f"- Кто ты: {scenario.caller.strip()}")
    if scenario.caller_role:
        lines.append(f"- Твоё отношение к происшествию: {ROLE_TEXT[scenario.caller_role]}")
    if scenario.contact_phone:
        lines.append(f"- Твой телефон для связи: {scenario.contact_phone}")
    if scenario.caller_phone_onsite:
        lines.append(f"- Телефон на месте происшествия: {scenario.caller_phone_onsite}")
    for flag in scenario.flags or []:
        if flag in FLAG_FACTS:
            lines.append(f"- Ещё: {FLAG_FACTS[flag]}")
    return "\n".join(lines)


def history_of(attempt: Attempt) -> list[tuple[str, str]]:
    return [(t["question"], t["answer"]) for t in (attempt.dialogue or [])]


async def ask(attempt: Attempt, question: str, provider: LLMProvider) -> CallerReply:
    """Спрашивает заявителя и, если он ответил, дописывает ход в попытку."""
    reply = await provider.caller_reply(
        facts=facts_for(attempt.scenario),
        history=history_of(attempt),
        question=question,
        difficulty=DIFFICULTY_TEXT.get(attempt.scenario.difficulty, "средняя"),
    )
    if reply.available:
        # Новый список, а не append: JSON-столбец замечает только присваивание.
        attempt.dialogue = [
            *(attempt.dialogue or []),
            {"question": question, "answer": reply.text, "at": utcnow().isoformat()},
        ]
    return reply
