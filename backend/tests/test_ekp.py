"""Проверка резолвера ЕКП на правилах, сверенных с исходным классификатором."""

import pytest

from app.services.ekp import get_ekp

# Горящий мусорный контейнер на улице: «на улице / мусор / открытое пламя».
FIRE_TRASH = 1010101


@pytest.fixture(scope="module")
def ekp():
    return get_ekp()


def test_классификатор_загружен_полностью(ekp):
    assert len(ekp) == 1283
    assert len(ekp.groups) == 23
    assert "Пожары и задымления" in ekp.groups


def test_признаки_задают_итоговый_тип(ekp):
    rule = ekp.rule(FIRE_TRASH)
    assert rule.signs == ("на улице", "мусор", "открытое пламя")
    assert rule.incident_type == "пожар: мусор"
    assert rule.main_service == "MCHS"


def test_без_флагов_экстренные_службы_не_оповещаются(ekp):
    """У пожара мусора без пострадавших нет повода звать МВД, СМП и ЦЭМП."""
    notified = ekp.rule(FIRE_TRASH).resolve()
    assert "Классификатор МЧС" in notified
    assert "Классификатор МВД" not in notified
    assert "Классификатор СМП" not in notified
    assert "ЦЭМП" not in notified


def test_флаг_пострадавшие_расширяет_список_оповещения(ekp):
    rule = ekp.rule(FIRE_TRASH)
    base = rule.resolve()
    with_victims = rule.resolve({"пострадавшие"})
    assert set(base) < set(with_victims)
    assert with_victims["Классификатор МВД"] == "пожар"
    assert with_victims["ЦЭМП"] == "карточка-112"


def test_служба_видит_происшествие_под_своим_названием(ekp):
    """Итоговый тип системы-112 и тип в системе службы могут не совпадать."""
    notified = ekp.rule(FIRE_TRASH).resolve({"пострадавшие"})
    assert notified["Классификатор МЧС"] == "пожар: мусор"
    assert notified["Классификатор МВД"] == "пожар"


def test_нет_реагирования_не_попадает_в_список(ekp):
    """Служебное значение «нет реагирования» означает отсутствие реагирования."""
    rule = ekp.rule(FIRE_TRASH)
    resolved = rule.resolve({"пострадавшие_не_на_месте"})
    assert "Классификатор СМП" not in resolved
    assert any(
        not n.responds for n in rule.notifications if n.service == "Классификатор СМП"
    )


def test_флаги_не_меняют_итоговый_тип(ekp):
    rule = ekp.rule(FIRE_TRASH)
    assert rule.incident_type == "пожар: мусор"
    assert len(rule.resolve({"пострадавшие", "газификация"})) > len(rule.resolve())


def test_выборка_правил_по_службе(ekp):
    rules = ekp.services_for("Мослифт")
    assert rules
    assert all(any(n.service == "Мослифт" for n in r.notifications) for r in rules)
