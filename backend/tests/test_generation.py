"""Проверка формирования сценариев: то, что берётся из классификатора, а не из модели."""

import random

import pytest

from app.services.ekp import get_ekp
from app.services.generation import _drop_self_referral, is_profile_for, pick_rules

LIFT_STUCK = 14100100


def test_профильность_следует_из_классификатора():
    """Мослифт оповещается о застревании в лифте, ДДС района — тоже, а ФСО нет."""
    rule = get_ekp().rule(LIFT_STUCK)
    assert is_profile_for(rule, "Мослифт") is True
    assert is_profile_for(rule, "ФСО") is False


def test_в_выборку_попадают_и_непрофильные():
    """Иначе обучающийся привыкает всегда нажимать «Принята»."""
    rules = pick_rules(
        "Аварии и происшествия в городском хозяйстве", 6, "Мослифт", random.Random(3)
    )
    assert len(rules) == 6
    profile = [r for r in rules if is_profile_for(r, "Мослифт")]
    assert 0 < len(profile) < len(rules)


def test_выборка_воспроизводима_по_зерну():
    args = ("Аварии и происшествия в городском хозяйстве", 5, "Мослифт")
    first = [r.number for r in pick_rules(*args, random.Random(42))]
    second = [r.number for r in pick_rules(*args, random.Random(42))]
    assert first == second


def test_пустая_группа_не_ломает_выборку():
    assert pick_rules("Такой группы нет", 5, "Мослифт", random.Random(1)) == []


@pytest.mark.parametrize(
    "point,kept",
    [
        ("информация передана в Мослифт", False),
        ("информация передана в диспетчерскую «Практика»", True),
        ("прибыла аварийная бригада Мослифт", True),
        ("сведения переданы в МОЭСК", True),
    ],
)
def test_пункт_о_передаче_самому_себе_отбрасывается(point, kept):
    """Раскрыть такой пункт обучающийся не смог бы при всём желании."""
    result = _drop_self_referral((point,), "Мослифт")
    assert (point in result) is kept


def test_число_обязательных_пунктов_ограничено():
    """Модель под влиянием замечания перечисляла все службы подряд."""
    from app.services.generation import MAX_COMMENT_POINTS

    assert MAX_COMMENT_POINTS == 3
