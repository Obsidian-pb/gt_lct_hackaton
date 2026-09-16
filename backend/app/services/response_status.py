"""Автомат статусов реагирования диспетчера ДДС.

Правила взяты из «Работа на АРМ-112. Памятка для дежурно-диспетчерских служб»
(ГБУ «Система 112», 2025), разделы «Статусы реагирования» и «Проставление
статусов реагирования».
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResponseStatus(StrEnum):
    ADDED = "Добавлена"
    RECEIVED = "Получена службой"
    ACCEPTED = "Принята"
    REJECTED = "Не принята"
    RESPONSE_STARTED = "Начало реагирования"
    ARRIVED = "Прибытие"
    WORK_IN_PROGRESS = "Проведение работ"
    WORK_COMPLETED = "Работы завершены"
    WORK_REFUSED = "Отказ от выполнения работ"


# Статусы, которые проставляет система, а не диспетчер.
AUTOMATIC = frozenset({ResponseStatus.ADDED, ResponseStatus.RECEIVED})

# Первичные статусы — те, что обязаны быть проставлены в течение норматива.
PRIMARY = frozenset({ResponseStatus.ACCEPTED, ResponseStatus.REJECTED})

# Закрывают карточку для редактирования.
TERMINAL = frozenset({ResponseStatus.WORK_COMPLETED, ResponseStatus.WORK_REFUSED})

# Комментарий обязателен: для отказов — с причиной и сведениями о передаче
# информации, для завершения работ — с результатами реагирования.
COMMENT_REQUIRED = frozenset(
    {ResponseStatus.REJECTED, ResponseStatus.WORK_REFUSED, ResponseStatus.WORK_COMPLETED}
)

_PROGRESS = (
    ResponseStatus.RESPONSE_STARTED,
    ResponseStatus.ARRIVED,
    ResponseStatus.WORK_IN_PROGRESS,
    ResponseStatus.WORK_COMPLETED,
    ResponseStatus.WORK_REFUSED,
)

TRANSITIONS: dict[ResponseStatus | None, tuple[ResponseStatus, ...]] = {
    None: (ResponseStatus.ACCEPTED, ResponseStatus.REJECTED),
    ResponseStatus.ADDED: (ResponseStatus.ACCEPTED, ResponseStatus.REJECTED),
    ResponseStatus.RECEIVED: (ResponseStatus.ACCEPTED, ResponseStatus.REJECTED),
    # Ошибочное «Не принята» исправляется только переходом в «Принята».
    ResponseStatus.REJECTED: (ResponseStatus.ACCEPTED,),
    ResponseStatus.ACCEPTED: _PROGRESS,
    ResponseStatus.RESPONSE_STARTED: _PROGRESS[1:],
    ResponseStatus.ARRIVED: _PROGRESS[2:],
    ResponseStatus.WORK_IN_PROGRESS: _PROGRESS[3:],
    ResponseStatus.WORK_COMPLETED: (),
    ResponseStatus.WORK_REFUSED: (),
}


class TransitionError(ValueError):
    pass


@dataclass(frozen=True)
class TransitionCheck:
    allowed: bool
    reason: str | None = None


def available_transitions(current: ResponseStatus | None) -> tuple[ResponseStatus, ...]:
    return TRANSITIONS[current]


def check_transition(
    current: ResponseStatus | None,
    target: ResponseStatus,
    comment: str | None = None,
    *,
    require_comment: bool = True,
) -> TransitionCheck:
    """Проверяет переход. require_comment=False проверяет только граф переходов,
    чтобы отсутствие комментария не засчитывалось нарушением дважды."""
    if target in AUTOMATIC:
        return TransitionCheck(False, f"Статус «{target}» проставляется системой автоматически")
    if current in TERMINAL:
        return TransitionCheck(False, f"Карточка закрыта для редактирования статусом «{current}»")
    if target not in TRANSITIONS[current]:
        allowed = ", ".join(f"«{s}»" for s in TRANSITIONS[current]) or "нет доступных"
        return TransitionCheck(
            False, f"Из статуса «{current}» нельзя перейти в «{target}». Доступно: {allowed}"
        )
    if require_comment and target in COMMENT_REQUIRED and not (comment or "").strip():
        return TransitionCheck(False, f"Статус «{target}» требует комментария")
    return TransitionCheck(True)


def apply_transition(
    current: ResponseStatus | None, target: ResponseStatus, comment: str | None = None
) -> ResponseStatus:
    check = check_transition(current, target, comment)
    if not check.allowed:
        raise TransitionError(check.reason)
    return target
