"""Инсайты в отчёте преподавателя: выводы по типичным ошибкам группы."""

import collections

from app.services.report import _insights

DEADLINE = 30


def test_без_завершённых_карточек_отчёт_говорит_об_этом():
    notes = _insights(collections.Counter(), 0, 0.0, DEADLINE)
    assert "ни одна карточка не завершена" in notes[0]


def test_частое_нарушение_попадает_в_выводы():
    notes = _insights(collections.Counter({"V4": 4}), 6, 0.0, DEADLINE)
    assert any("Нет комментария" in n for n in notes)


def test_редкое_нарушение_не_попадает():
    """Одно нарушение на десять карточек — не системная ошибка группы."""
    notes = _insights(collections.Counter({"V4": 1}), 10, 0.0, DEADLINE)
    assert not any("Нет комментария" in n for n in notes)


def test_нарушение_норматива_упоминается_отдельно():
    notes = _insights(collections.Counter(), 10, 0.4, DEADLINE)
    assert "Норматив взятия в работу" in notes[0]
    assert "40%" in notes[0]


def test_ошибки_оператора_112_не_теряются():
    """Занятие оператора даёт коды другого каталога.

    Раньше отчёт смотрел только в каталог диспетчера и при восьми
    нарушениях сообщал преподавателю, что системных ошибок не видно.
    """
    notes = _insights(collections.Counter({"O3": 5, "O4": 3}), 6, 0.0, DEADLINE)
    assert any("Неверный итоговый тип происшествия" in n for n in notes)
    assert any("Не оповещены службы" in n for n in notes)
    assert not any("системных ошибок не видно" in n for n in notes)


def test_критические_нарушения_замечаются_даже_поодиночке():
    """Каждое встретилось редко, но все критические — молчать нельзя."""
    notes = _insights(collections.Counter({"O1": 1, "O5": 1}), 20, 0.0, DEADLINE)
    assert "Критических нарушений: 2" in " ".join(notes)


def test_чистая_группа():
    notes = _insights(collections.Counter(), 10, 0.0, DEADLINE)
    assert "в пределах регламента" in notes[0]
