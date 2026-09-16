"""Проверка оценщика на реальных примерах нарушений из памятки ГБУ «Система 112»."""

import pytest

from app.services.evaluation import Expectation, StatusEvent, evaluate
from app.services.response_status import ResponseStatus as S


def codes(assessment):
    return sorted({v.code for v in assessment.violations})


def test_принята_в_срок_без_нарушений():
    result = evaluate(
        [StatusEvent(S.ACCEPTED, 12.0)],
        Expectation(primary_status=S.ACCEPTED, is_profile=True),
    )
    assert result.violations == []
    assert result.score == 1.0
    assert all(result.criteria.values())


def test_статус_не_проставлен_вовсе():
    """Карточка уходит в «Не оповещено» — нарушение № 1 памятки."""
    result = evaluate([], Expectation(primary_status=S.ACCEPTED, is_profile=True))
    assert codes(result) == ["V1"]
    assert result.primary_status is None


def test_опоздание_с_первичным_статусом():
    result = evaluate(
        [StatusEvent(S.ACCEPTED, 47.0)],
        Expectation(primary_status=S.ACCEPTED, is_profile=True),
    )
    assert codes(result) == ["V1"]
    assert "17 с" in result.violations[0].detail


def test_принята_вместо_не_принята_повреждение_дорожного_покрытия():
    """Пример из памятки: «Принята: не обслуживаем территорию» вместо «Не принята»."""
    result = evaluate(
        [StatusEvent(S.ACCEPTED, 10.0, "не обслуживаем территорию")],
        Expectation(primary_status=S.REJECTED, is_profile=False),
    )
    assert codes(result) == ["V2"]


def test_отказ_от_профильного_происшествия():
    """Пример из памятки: посторонние граждане в подвале, «Не принята» без причины."""
    result = evaluate(
        [StatusEvent(S.REJECTED, 15.0, "не в компетенции")],
        Expectation(primary_status=S.ACCEPTED, is_profile=True),
    )
    assert codes(result) == ["V3"]
    assert result.criteria[list(result.criteria)[1]] is False  # компетенция службы


def test_не_принята_без_комментария():
    """Пример из памятки: пожарная сигнализация, дом обслуживает УК «ПИК»."""
    result = evaluate(
        [StatusEvent(S.REJECTED, 8.0, comment=None)],
        Expectation(primary_status=S.REJECTED, is_profile=False),
    )
    assert codes(result) == ["V4"]


def test_нарушена_последовательность_статусов():
    """Прибытие без предшествующего «Принята» недопустимо."""
    result = evaluate(
        [StatusEvent(S.ARRIVED, 5.0), StatusEvent(S.ACCEPTED, 9.0)],
        Expectation(primary_status=S.ACCEPTED, is_profile=True),
    )
    assert "V7" in codes(result)


def test_нет_статусов_хода_работ():
    """Пример из памятки: прорыв трубы, работы велись, но в карточку не вносились."""
    result = evaluate(
        [StatusEvent(S.ACCEPTED, 11.0)],
        Expectation(
            primary_status=S.ACCEPTED, is_profile=True, expects_progress_statuses=True
        ),
    )
    assert codes(result) == ["V6"]


def test_карточка_закрыта_после_завершения_работ():
    result = evaluate(
        [
            StatusEvent(S.ACCEPTED, 10.0),
            StatusEvent(S.WORK_COMPLETED, 60.0, "работы завершены, течь устранена"),
            StatusEvent(S.ARRIVED, 90.0),
        ],
        Expectation(primary_status=S.ACCEPTED, is_profile=True),
    )
    assert "V7" in codes(result)


@pytest.mark.parametrize(
    "penalty_events,expected_score",
    [([StatusEvent(S.ACCEPTED, 12.0)], 1.0), ([], 1.0 - 1.0 / 3.0)],
)
def test_шкала_оценки(penalty_events, expected_score):
    result = evaluate(
        penalty_events, Expectation(primary_status=S.ACCEPTED, is_profile=True)
    )
    assert result.score == pytest.approx(expected_score)
