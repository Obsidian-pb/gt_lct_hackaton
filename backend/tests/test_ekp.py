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
    assert "МЧС" in notified
    assert "МВД" not in notified
    assert "СМП" not in notified
    assert "ЦЭМП" not in notified


def test_флаг_пострадавшие_расширяет_список_оповещения(ekp):
    rule = ekp.rule(FIRE_TRASH)
    base = rule.resolve()
    with_victims = rule.resolve({"пострадавшие"})
    assert set(base) < set(with_victims)
    assert with_victims["МВД"] == "пожар"
    assert with_victims["ЦЭМП"] == "карточка-112"


def test_служба_видит_происшествие_под_своим_названием(ekp):
    """Итоговый тип системы-112 и тип в системе службы могут не совпадать."""
    notified = ekp.rule(FIRE_TRASH).resolve({"пострадавшие"})
    assert notified["МЧС"] == "пожар: мусор"
    assert notified["МВД"] == "пожар"


def test_нет_реагирования_не_попадает_в_список(ekp):
    """Служебное значение «нет реагирования» означает отсутствие реагирования."""
    rule = ekp.rule(FIRE_TRASH)
    resolved = rule.resolve({"пострадавшие_не_на_месте"})
    assert "СМП" not in resolved
    assert any(
        not n.responds for n in rule.notifications if n.service == "СМП"
    )


def test_флаги_не_меняют_итоговый_тип(ekp):
    rule = ekp.rule(FIRE_TRASH)
    assert rule.incident_type == "пожар: мусор"
    assert len(rule.resolve({"пострадавшие", "газификация"})) > len(rule.resolve())


# --- Обоснование списка оповещения -------------------------------------------


def test_обоснование_повторяет_список_оповещения(ekp):
    """Оповещённые в обосновании — ровно те, что в списке, и в том же порядке."""
    rule = ekp.rule(FIRE_TRASH)
    for flags in (set(), {"пострадавшие"}, {"газификация", "угроза_людям"}):
        reasons = rule.explain(flags)
        assert [r.service for r in reasons if r.notified] == list(rule.resolve(flags))
        assert {r.service: r.incident_type_in_service for r in reasons if r.notified} == rule.resolve(flags)


def test_служба_без_признака_объясняется_как_постоянная(ekp):
    reasons = {r.service: r for r in ekp.rule(FIRE_TRASH).explain()}
    assert reasons["МЧС"].kind == "always"
    assert reasons["МЧС"].notified is True
    assert "всегда" in reasons["МЧС"].text


def test_служба_по_признаку_называет_признак(ekp):
    reasons = {r.service: r for r in ekp.rule(FIRE_TRASH).explain({"пострадавшие"})}
    assert reasons["СМП"].kind == "flag"
    assert reasons["СМП"].flags == ("пострадавшие",)
    assert reasons["СМП"].text == "потому что отмечен признак «пострадавшие»"


def test_неоповещённая_служба_подсказывает_признак(ekp):
    """Именно это и есть урок: скорая появится, если отметить пострадавших."""
    reasons = {r.service: r for r in ekp.rule(FIRE_TRASH).explain()}
    smp = reasons["СМП"]
    assert smp.notified is False
    assert smp.kind == "conditional"
    assert "пострадавшие" in smp.flags
    # Подколонка «нет реагирования» службу не добавляет — её признак не подсказывается.
    assert "пострадавшие_не_на_месте" not in smp.flags
    assert "только при признаке" in smp.text and "не отмечен" in smp.text


def test_обоснование_не_выдумывает_служб(ekp):
    """Службы, которых у правила нет ни в одной подколонке, не упоминаются."""
    rule = ekp.rule(FIRE_TRASH)
    listed = {r.service for r in rule.explain({"пострадавшие"})}
    assert listed <= {n.service for n in rule.notifications}


def test_выборка_правил_по_службе(ekp):
    rules = ekp.services_for("Мослифт")
    assert rules
    assert all(any(n.service == "Мослифт" for n in r.notifications) for r in rules)
