"""Оценка работы оператора Службы 112: классификация и оформление карточки."""

import pytest

from app.services.operator import DEFAULT_CALL_DEADLINE_SECONDS, FilledCard, evaluate

FIRE_TRASH = 1010101  # на улице / мусор / открытое пламя
FIRES = "Пожары и задымления"
RIGHT_PATH = ("на улице", "мусор", "открытое пламя")


def card(**kwargs) -> FilledCard:
    defaults = dict(
        group=FIRES,
        path=RIGHT_PATH,
        address="Москва, ул. Кировоградская, д. 24",
        description="Горит мусорный контейнер во дворе, пострадавших нет",
        elapsed_seconds=90.0,
    )
    return FilledCard(**{**defaults, **kwargs})


def codes(assessment):
    return sorted({v.code for v in assessment.violations})


def check(**kwargs):
    return evaluate(card(**kwargs), FIRE_TRASH, DEFAULT_CALL_DEADLINE_SECONDS)


def test_безошибочная_обработка_вызова():
    result = check()
    assert result.violations == []
    assert result.classification.correct is True
    assert result.score == 1.0


def test_признаки_не_выбраны():
    result = check(group=None, path=())
    assert "O1" in codes(result)
    assert result.classification is None
    assert result.score < 0.4


def test_неверная_группа_происшествий():
    result = check(group="Нарушение правопорядка", path=("Подозрительные, посторонние граждане",))
    assert "O2" in codes(result)
    assert result.classification.same_group is False


def test_ошибка_в_признаке_даёт_частичный_балл():
    """Дым вместо открытого пламени: путь начат верно, тип всё же другой."""
    result = check(path=("на улице", "мусор", "дым"))
    assert "O3" in codes(result)
    assert 0 < result.score < 1.0


def test_разбор_называет_неоповещённые_службы():
    """Главное последствие ошибки — на происшествие не поедет нужная служба."""
    result = check(path=("на улице", "мусор", "дым"))
    missed = [v for v in result.violations if v.code == "O4"]
    if missed:
        assert "не были бы оповещены" in missed[0].detail


def test_адрес_обязателен():
    result = check(address="   ")
    assert "O5" in codes(result)
    assert result.score < 1.0


def test_описание_обязательно():
    result = check(description="")
    assert "O6" in codes(result)


def test_превышение_ориентира_снижает_балл_но_не_нарушение():
    """Разговор может затянуться по вине заявителя — это не проступок."""
    fast = check(elapsed_seconds=60.0)
    slow = check(elapsed_seconds=400.0)
    assert slow.violations == fast.violations == []
    assert slow.score < fast.score


@pytest.mark.parametrize("path", [("на улице",), ("на улице", "мусор")])
def test_недоведённая_классификация(path):
    result = check(path=path)
    assert "O1" in codes(result)
    assert result.classification.chosen_rule is None
