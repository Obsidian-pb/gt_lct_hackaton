"""Оценка работы оператора Службы 112: классификация и оформление карточки."""

import pytest

from app.api.operator import _audio_url
from app.models.training import Scenario, ScenarioSource
from app.models.training import CallOutcome
from app.services.operator import (
    DEFAULT_CALL_DEADLINE_SECONDS,
    Expected,
    FilledCard,
    evaluate,
)

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


def scenario(title: str, source: ScenarioSource) -> Scenario:
    return Scenario(title=title, source=source)


def test_запись_вызова_находится_по_номеру_билета():
    """Файлы озвучены заранее и названы по билету и номеру вызова в нём."""
    ticket = scenario("Билет 12, вызов 3", ScenarioSource.TICKET)
    assert _audio_url(ticket) == "/audio/ticket-12-3.mp3"


@pytest.mark.parametrize(
    "title,source",
    [
        # Сценарии, придуманные нейросетью, никто не озвучивал.
        ("Возгорание мусора во дворе", ScenarioSource.GENERATED),
        # Название билета могли поправить вручную — тогда файла тоже нет.
        ("Билет без номера", ScenarioSource.TICKET),
    ],
)
def test_без_записи_вызов_остаётся_текстовым(title, source):
    assert _audio_url(scenario(title, source)) is None


# --- Исход обращения: не всякий вызов надо классифицировать ------------------
#
# Экзаменационные билеты Службы 112 проверяют это прямо: из 96 вызовов
# 18 происходят в других субъектах, а один вовсе не является происшествием.
# До сих пор такие вызовы в занятия не заводились.

TULA = Expected(
    outcome=CallOutcome.REFER,
    referral_target="Тульская область",
)
NOT_INCIDENT = Expected(outcome=CallOutcome.REJECT)
MOSCOW_FIRE = Expected(outcome=CallOutcome.CLASSIFY, rule_number=FIRE_TRASH)


def outcome_card(**kwargs) -> FilledCard:
    defaults = dict(
        group=None,
        path=(),
        address="Тульская обл., дорога от Киреевска в сторону Октябрьского",
        description="Съезд автомобиля в кювет, пострадавших нет",
        elapsed_seconds=90.0,
        outcome=CallOutcome.REFER,
        referral_target="Тульская область",
    )
    return FilledCard(**{**defaults, **kwargs})


def test_передача_по_принадлежности_без_замечаний():
    result = evaluate(outcome_card(), TULA, DEFAULT_CALL_DEADLINE_SECONDS)
    assert result.violations == []
    assert result.outcome_correct is True
    assert result.score == 1.0


def test_чужой_регион_классифицирован_как_московский():
    """Самая дорогая ошибка: московские силы туда не поедут."""
    result = evaluate(
        outcome_card(outcome=CallOutcome.CLASSIFY, group=FIRES, path=RIGHT_PATH),
        TULA,
        DEFAULT_CALL_DEADLINE_SECONDS,
    )
    assert codes(result) == ["O7"]
    assert result.outcome_correct is False
    assert result.score == 0.0
    assert "Тульская область" in result.violations[0].detail


def test_передача_без_указания_субъекта():
    result = evaluate(
        outcome_card(referral_target=""), TULA, DEFAULT_CALL_DEADLINE_SECONDS
    )
    assert codes(result) == ["O9"]
    # Исход верный, поэтому балл снижается, а не обнуляется.
    assert result.outcome_correct is True
    assert 0.0 < result.score < 1.0


def test_передача_не_в_тот_субъект():
    result = evaluate(
        outcome_card(referral_target="Рязанская область"),
        TULA,
        DEFAULT_CALL_DEADLINE_SECONDS,
    )
    assert codes(result) == ["O9"]


def test_столица_не_засчитывается_за_область():
    """«Москва» вместо «Московской области» — то самое смешение, которое
    вызов и проверяет."""
    result = evaluate(
        outcome_card(referral_target="Москва"),
        Expected(outcome=CallOutcome.REFER, referral_target="Московская область"),
        DEFAULT_CALL_DEADLINE_SECONDS,
    )
    assert codes(result) == ["O9"]


def test_сокращение_субъекта_принимается():
    result = evaluate(
        outcome_card(referral_target="МО"),
        Expected(outcome=CallOutcome.REFER, referral_target="Московская область"),
        DEFAULT_CALL_DEADLINE_SECONDS,
    )
    assert result.violations == []


def test_не_происшествие_отклонено_верно():
    result = evaluate(
        outcome_card(
            outcome=CallOutcome.REJECT,
            address="Москва, Сущевский Вал, дом 5, строение 1",
            description="Ссора с продавцом салона связи",
        ),
        NOT_INCIDENT,
        DEFAULT_CALL_DEADLINE_SECONDS,
    )
    assert result.violations == []
    assert result.score == 1.0


def test_не_происшествие_зарегистрировано():
    result = evaluate(
        outcome_card(outcome=CallOutcome.CLASSIFY, group=FIRES, path=RIGHT_PATH),
        NOT_INCIDENT,
        DEFAULT_CALL_DEADLINE_SECONDS,
    )
    assert codes(result) == ["O10"]
    assert result.score == 0.0


@pytest.mark.parametrize("wrong", [CallOutcome.REFER, CallOutcome.REJECT])
def test_московское_происшествие_не_передают_и_не_отклоняют(wrong):
    """Обратная ошибка не легче: на происшествие не выедет никто."""
    result = evaluate(
        card(outcome=wrong, referral_target="Тульская область"),
        MOSCOW_FIRE,
        DEFAULT_CALL_DEADLINE_SECONDS,
    )
    assert codes(result) == ["O8"]
    assert result.score == 0.0


def test_при_передаче_адрес_и_описание_всё_равно_нужны():
    """Передавать вызов без адреса некуда, даже если субъект назван верно.

    Балл при этом не обнуляется: решение о судьбе обращения принято верно,
    а незаполненные поля — отдельная, менее тяжёлая ошибка. Обнуление
    оставлено за неверным исходом.
    """
    result = evaluate(
        outcome_card(address="", description=""), TULA, DEFAULT_CALL_DEADLINE_SECONDS
    )
    assert codes(result) == ["O5", "O6"]
    assert result.score == 0.25


def test_прежние_вызовы_с_номером_правила_работают_как_раньше():
    """Совместимость: эталон числом означает исход «классифицировать»."""
    result = evaluate(card(), FIRE_TRASH, DEFAULT_CALL_DEADLINE_SECONDS)
    assert result.violations == []
    assert result.score == 1.0


# --- Телефон для связи -------------------------------------------------------
#
# Поля заявителя взяты из разбора карточки происшествия, который сделал
# заказчик: три телефона и статус. Здесь проверяется главное из них —
# записан ли номер, по которому силы реагирования свяжутся с заявителем.

WITH_PHONE = Expected(
    outcome=CallOutcome.CLASSIFY,
    rule_number=FIRE_TRASH,
    contact_phone="916-126-34-71",
)


def test_телефон_записан_верно():
    result = evaluate(
        card(caller_phone="916-126-34-71"), WITH_PHONE, DEFAULT_CALL_DEADLINE_SECONDS
    )
    assert result.violations == []


@pytest.mark.parametrize(
    "written",
    ["8 916 126 34 71", "+7 (916) 126-34-71", "9161263471", " 916 126 3471 "],
)
def test_форма_записи_номера_не_важна(written):
    """Оператор записывает номер на слух, разделители у каждого свои."""
    result = evaluate(card(caller_phone=written), WITH_PHONE, DEFAULT_CALL_DEADLINE_SECONDS)
    assert result.violations == []


def test_телефон_не_записан():
    result = evaluate(card(caller_phone=""), WITH_PHONE, DEFAULT_CALL_DEADLINE_SECONDS)
    assert codes(result) == ["O11"]
    assert "не внесён" in result.violations[0].detail


def test_записан_чужой_номер():
    result = evaluate(
        card(caller_phone="916-000-00-00"), WITH_PHONE, DEFAULT_CALL_DEADLINE_SECONDS
    )
    assert codes(result) == ["O11"]
    assert "заявитель назвал другой" in result.violations[0].detail


def test_телефон_не_спрашивается_если_его_нет_в_сценарии():
    """У части учебных вызовов телефона нет — требовать его было бы придиркой."""
    result = evaluate(card(caller_phone=""), FIRE_TRASH, DEFAULT_CALL_DEADLINE_SECONDS)
    assert result.violations == []


def test_номер_со_слов_важнее_определившегося():
    """Заявитель звонит с чужого телефона и называет свой — записывать его."""
    from app.models.training import Scenario

    scenario = Scenario(
        caller_phone_aon="495-111-22-33", caller_phone_stated="916-126-34-71"
    )
    assert scenario.contact_phone == "916-126-34-71"
    only_aon = Scenario(caller_phone_aon="495-111-22-33")
    assert only_aon.contact_phone == "495-111-22-33"
