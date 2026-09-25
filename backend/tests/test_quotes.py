"""Цитаты из речи заявителя к замечаниям."""

from app.services import quotes
from app.services.survey_flags import pattern_for


def test_фрагмент_вокруг_найденного_обрезается_по_словам():
    text = "Москва, ул. Знаменские Садки, дом 7 корп.2, кв. 216, под. 4, эт. 4, код 216"
    quote = quotes.find(text, "216")
    assert quote is not None and "216" in quote
    assert quote.startswith("…") and not quote.startswith("… ")


def test_поиск_без_учёта_регистра_и_ё():
    assert quotes.find("Горит Берёзовая аллея", "березовая аллея") is not None


def test_телефон_находится_при_любых_разделителях():
    text = "Иванова Елена Сергеевна, 916 896 3254, стоит рядом"
    quote = quotes.find_digits(text, "916-896-32-54")
    assert quote is not None and "916 896 3254" in quote


def test_короткие_числа_за_телефон_не_принимаются():
    assert quotes.find_digits("дом 21, корпус 1", "21") is None


def test_ненайденное_не_сочиняется():
    assert quotes.find("Горит мусорный контейнер", "Берзарина") is None
    assert quotes.find_digits("без номера", "9161263471") is None


def test_признак_цитируется_по_месту_упоминания():
    text = "Дерутся 10-15 человек, 5 пострадавших с различными травмами, дерутся палками"
    quote = quotes.find_any(text, pattern_for("пострадавшие"))
    assert quote is not None and "5 пострадавших" in quote
