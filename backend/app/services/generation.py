"""Формирование учебных сценариев по классификатору и языковой модели.

Роли разделены намеренно. Классификатор задаёт то, что проверяемо: какой тип
происшествия существует, какие у него признаки и попадает ли служба
обучающегося в список оповещения. Модель придумывает только фабулу — описание,
адрес, заявителя и обязательные пункты комментария.

Поэтому профильность происшествия не выдумывается: она следует из ЕКП. Если
служба есть в списке оповещения, эталон — «Принята», если нет — «Не принята»
с передачей информации по принадлежности.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

from app.llm import GeneratedScenario, LLMProvider
from app.services.callers import random_caller
from app.services.ekp import Rule, get_ekp
from app.services.response_status import ResponseStatus

DIFFICULTY_LABELS = {1: "простая", 2: "средняя", 3: "высокая"}

# Требование к числу пунктов в промпте модель соблюдает не всегда: под влиянием
# замечания преподавателя она перечисляла все оповещаемые службы подряд.
# Комментарий из семи обязательных фактов обучающийся не напишет за 30 секунд.
MAX_COMMENT_POINTS = 3


@dataclass(frozen=True)
class DraftScenario:
    """Черновик до утверждения преподавателем."""

    ekp_rule_number: int
    incident_type: str
    group: str
    signs: tuple[str, ...]
    description: str
    address: str
    caller: str
    expected_primary_status: ResponseStatus
    is_profile: bool
    required_comment_points: tuple[str, ...]
    difficulty: int
    notified_services: dict[str, str]


def _drop_self_referral(points: tuple[str, ...], service: str) -> tuple[str, ...]:
    """Убирает пункты вида «информация передана в <своя же служба>».

    Комментарий пишет сама служба, поэтому передать сведения себе она не может.
    Модель эту тонкость усваивает не всегда, а такой пункт заведомо невыполним:
    обучающийся не сможет его раскрыть, как бы ни старался.
    """
    key = service.lower().split("(")[0].strip()
    return tuple(
        p
        for p in points
        if not ("передан" in p.lower() and key and key in p.lower())
    )


def is_profile_for(rule: Rule, service: str, flags: set[str] | None = None) -> bool:
    """Попадает ли служба в список оповещения по этому происшествию."""
    return service in rule.resolve(flags or set())


def pick_rules(group: str, count: int, service: str, rng: random.Random) -> list[Rule]:
    """Выбирает правила группы, подмешивая непрофильные.

    Тренажёр должен учить и отказываться: если все карточки профильные,
    обучающийся привыкает всегда нажимать «Принята», а корректный отказ —
    отдельный навык, которому посвящён целый раздел памятки.
    """
    rules = list(get_ekp().by_group(group))
    if not rules:
        return []

    profile = [r for r in rules if is_profile_for(r, service)]
    other = [r for r in rules if not is_profile_for(r, service)]
    rng.shuffle(profile)
    rng.shuffle(other)

    # Примерно каждая третья карточка — непрофильная, если такие есть.
    wanted_other = min(len(other), max(1, count // 3)) if other else 0
    chosen = profile[: count - wanted_other] + other[:wanted_other]
    if len(chosen) < count:
        chosen += (profile + other)[len(chosen) : count]
    rng.shuffle(chosen)
    return chosen[:count]


async def draft_from_rule(
    provider: LLMProvider,
    rule: Rule,
    service: str,
    difficulty: int,
    note: str | None = None,
    rng: random.Random | None = None,
) -> DraftScenario | None:
    profile = is_profile_for(rule, service)
    notified = rule.resolve()
    generated: GeneratedScenario = await provider.generate_scenario(
        incident_type=rule.incident_type,
        group=rule.group,
        difficulty=DIFFICULTY_LABELS.get(difficulty, "средняя"),
        service=service,
        signs=list(rule.signs),
        note=note,
        is_profile=profile,
        other_services=[s for s in notified if s != service],
    )

    if not generated.available:
        return None

    status = ResponseStatus.ACCEPTED if profile else ResponseStatus.REJECTED
    return DraftScenario(
        ekp_rule_number=rule.number,
        incident_type=rule.incident_type,
        group=rule.group,
        signs=rule.signs,
        description=generated.incident_description,
        address=generated.address,
        caller=random_caller(rng),
        expected_primary_status=status,
        is_profile=profile,
        required_comment_points=_drop_self_referral(
            tuple(generated.required_comment_points), service
        )[:MAX_COMMENT_POINTS],
        difficulty=difficulty,
        notified_services=notified,
    )


async def generate_batch(
    provider: LLMProvider,
    group: str,
    count: int,
    service: str,
    difficulty: int = 2,
    seed: int | None = None,
    concurrency: int = 2,
) -> list[DraftScenario]:
    """Формирует пачку черновиков.

    Запросы к модели идут параллельно: последовательно два десятка карточек
    заняли бы полминуты, и преподаватель ждал бы у пустого экрана. Одновременность
    намеренно небольшая: GigaChat отвечает отказом по частоте уже при четырёх потоках.

    Черновики, которые модель не сформировала, в результат не попадают —
    показывать пустые карточки нельзя. Вызывающий сравнивает длину результата
    с запрошенным количеством и сообщает, сколько получилось.
    """
    rng = random.Random(seed)
    rules = pick_rules(group, count, service, rng)
    # Генератор случайных чисел не потокобезопасен, а заявители нужны разные,
    # поэтому раздаём каждой задаче собственное зерно заранее.
    seeds = [rng.random() for _ in rules]
    limit = asyncio.Semaphore(concurrency)

    async def one(rule: Rule, item_seed: float) -> DraftScenario | None:
        async with limit:
            return await draft_from_rule(
                provider, rule, service, difficulty, rng=random.Random(item_seed)
            )

    drafts = await asyncio.gather(*(one(r, s) for r, s in zip(rules, seeds)))
    return [d for d in drafts if d is not None]
