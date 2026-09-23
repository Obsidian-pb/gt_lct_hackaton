"""Разбор адреса на части и его сверка.

Примеры взяты из настоящих экзаменационных билетов: разбор обязан
справляться с тем, как люди на самом деле называют место, а не с
образцовыми адресами из справочника.
"""

import pytest

from app.services.address import DISPLAY_ONLY, PRESENCE_ONLY, compare, parse

# --- Объект и ориентиры -------------------------------------------------------


def test_станция_метро_становится_объектом():
    parts = parse("Москва, станция метро Арбатская")
    assert parts["object"] == "станция метро Арбатская"
    assert "access" not in parts


def test_двор_у_подъезда_становится_ориентиром():
    parts = parse("Москва, ул. Вешняковская дом 37, двор у 5 подъезда")
    assert parts["street"] == "Вешняковская"
    assert parts["house"] == "37"
    assert parts["access"] == "двор у 5 подъезда"
    assert "object" not in parts


def test_место_на_мкад_описывается_объектом_и_ориентирами():
    parts = parse(
        "Москва, МКАД, от Варшавского шоссе в сторону Каширского, напротив ТЦ Вегас, в левом ряду"
    )
    assert parts["subject"] == "Москва"
    assert "house" not in parts
    assert parts["object"] == "ТЦ Вегас"
    assert "в левом ряду" in parts["access"]
    assert "от Варшавского шоссе в сторону Каширского" in parts["access"]


def test_вводный_оборот_уходит_из_объекта():
    """«около магазина» — это ориентир; объект — сам магазин."""
    parts = parse("Москва, Дмитровское шоссе, дом 155 корп.1, около магазина «Пятерочка»")
    assert parts["object"] == "магазина «Пятерочка»"
    assert parts["access"] == "около магазина «Пятерочка»"


def test_один_кусок_даёт_и_объект_и_ориентир():
    parts = parse("Москва, Тихорецкий бульвар, дом 12 корп.1, во дворе у входа в магазин «Билла»")
    assert parts["object"] == "магазин «Билла»"
    assert parts["access"] == "во дворе у входа в магазин «Билла»"


def test_несколько_ориентиров_собираются_вместе():
    parts = parse("Москва, парк Лосиный остров, вход от улицы Красной сосны, далее по дорожке прямо до скамеек")
    assert parts["object"] == "парк Лосиный остров"
    assert parts["access"] == "вход от улицы Красной сосны; далее по дорожке прямо до скамеек"


def test_обычный_адрес_без_объекта_и_ориентиров():
    parts = parse("Москва, ул. Знаменские Садки, дом 7 корп.2, кв. 216, под. 4, эт. 4, код 216")
    assert "object" not in parts
    assert "access" not in parts
    assert parts["flat"] == "216"


def test_улица_не_принимается_за_объект_или_ориентир():
    """Кусок с улицей и домом — адрес, а не подсказка, как проехать."""
    parts = parse("Москва, ул. Красный Казанец дом 19Б, напротив дома, на стоянке")
    assert "object" not in parts
    assert parts["access"] == "напротив дома; на стоянке"


def test_округ_и_район_не_разбираются():
    """Их не называет заявитель — брать неоткуда, и выдумывать нельзя."""
    parts = parse("Москва, ЮЗАО, район Ясенево, ул. Вильнюсская, дом 4")
    for key in DISPLAY_ONLY:
        assert key not in parts


# --- Сверка ------------------------------------------------------------------

ON_RING_ROAD = {"subject": "Москва", "settlement": "Москва", "object": "ТЦ Вегас", "access": "напротив ТЦ Вегас, в левом ряду"}
IN_TOWN = {"subject": "Москва", "settlement": "Москва", "street": "Тихорецкий бульвар", "house": "12", "object": "магазин «Билла»", "access": "во дворе у входа"}


def test_ориентиры_без_дома_критичны():
    """По «МКАД» без «напротив ТЦ Вегас» экипаж будет ездить по кольцу."""
    check = compare(ON_RING_ROAD, {"subject": "Москва", "settlement": "Москва"})
    assert set(check.missing) == {"object", "access"}
    assert set(check.critical_missing) == {"object", "access"}


def test_ориентиры_при_известном_доме_не_критичны():
    check = compare(IN_TOWN, {k: v for k, v in IN_TOWN.items() if k not in PRESENCE_ONLY})
    assert set(check.missing) == {"object", "access"}
    assert check.critical_missing == ()


@pytest.mark.parametrize("written", ["Вегас", "торговый центр Вегас", "ТЦ «Вегас» справа"])
def test_объект_и_ориентиры_не_сверяются_дословно(written):
    """Свободный текст: важно, что записано, а не как сформулировано."""
    check = compare(ON_RING_ROAD, dict(ON_RING_ROAD, object=written, access="слева от дороги"))
    assert check.ok


def test_округ_и_район_не_требуются_даже_если_есть_в_эталоне():
    expected = dict(IN_TOWN, district="СВАО", area="Отрадное")
    check = compare(expected, dict(IN_TOWN))
    assert check.ok
