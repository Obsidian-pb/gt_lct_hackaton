"""Названия признаков опросной карты: кнопки должны называться как в АРМ-112."""

import pytest

from app.services import flags
from app.services.ekp import get_ekp

FIRE_TRASH = 1010101  # на улице / мусор / открытое пламя


@pytest.fixture(scope="module")
def ekp():
    return get_ekp()


def test_у_каждого_признака_классификатора_есть_название(ekp):
    """Кнопка без подписи ничему не учит: словарь обязан покрывать редакцию поставки."""
    missing = sorted(flags.known_keys(ekp) - set(flags.TITLES))
    assert missing == []


def test_глобальных_кнопок_ровно_три_и_в_порядке_карточки():
    titles = [f.title for f in flags.global_flags()]
    assert titles == [
        "Пострадавшие",
        "Нет на месте / Отказ от скорой",
        "Нет доступа / Заблокированные",
    ]


def test_неизвестный_ключ_получает_название_из_ключа():
    """Новая редакция может принести признак, о котором словарь не знает."""
    info = flags.describe("новый_признак")
    assert info.title == "Новый признак"
    assert info.hint == ""


def test_признаки_правила_без_глобальных(ekp):
    keys = [f.key for f in flags.flags_for_rule(ekp.rule(FIRE_TRASH))]
    assert "газификация" in keys
    assert "правонарушение" in keys
    assert not set(keys) & set(flags.GLOBAL_KEYS)
    # Каждый признак — одной кнопкой, сколько бы служб на него ни реагировало.
    assert len(keys) == len(set(keys))


def test_признак_без_реагирования_не_даёт_кнопки(ekp):
    """Подколонка с «нет реагирования» службу не добавляет — кнопка была бы пустой."""
    rule = ekp.rule(FIRE_TRASH)
    shown = {f.key for f in flags.flags_for_rule(rule)}
    silent = {
        key
        for n in rule.notifications
        if n.variant_kind == "flag" and not n.responds
        for key in n.requires_flags
    }
    responding = {
        key
        for n in rule.notifications
        if n.variant_kind == "flag" and n.responds
        for key in n.requires_flags
    }
    assert not (silent - responding) & shown


def test_допустимые_ключи_включают_глобальные(ekp):
    assert set(flags.GLOBAL_KEYS) <= flags.known_keys(ekp)
