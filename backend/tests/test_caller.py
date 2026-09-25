"""Заявитель на линии: вопросы оператора и ответы модели за заявителя."""

import pytest

from app.llm.base import CallerReply
from app.models.training import CallerRole, Scenario
from app.services import caller
from tests.test_operator_api import make_call, token


class EchoCaller:
    """Подставной заявитель: отвечает по факту, запоминает, что ему передали."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def caller_reply(self, *, facts, history, question, difficulty):
        self.calls.append({"facts": facts, "history": history, "question": question, "difficulty": difficulty})
        return CallerReply(available=True, text="Не знаю" if "домофон" in question else "Да, горит контейнер во дворе")


def test_факты_для_заявителя_без_классификатора():
    scenario = Scenario(
        description="Горит мусорный контейнер во дворе",
        address="Москва, ул. Кировоградская, д. 24",
        caller="Иванов И. И.",
        caller_role=CallerRole.WITNESS,
        caller_phone_stated="916-126-34-71",
        flags=["пострадавшие"],
        incident_type="пожар: мусор",
    )
    facts = caller.facts_for(scenario)
    assert "Горит мусорный контейнер" in facts and "Кировоградская" in facts
    assert "очевидец" in facts and "916-126-34-71" in facts and "есть пострадавшие" in facts
    # Тип по классификатору и службы заявителю не известны — их в фактах нет.
    assert "пожар: мусор" not in facts and "МЧС" not in facts


def test_вопрос_записывается_вместе_с_ответом(client, db_factory, monkeypatch):
    echo = EchoCaller()
    monkeypatch.setattr("app.api.operator.get_llm_provider", lambda: echo)
    attempt_id = make_call(db_factory)
    headers = token(client, "student")

    first = client.post(f"/api/operator/calls/{attempt_id}/ask", json={"question": "Что горит?"}, headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["available"] is True and body["turn"]["answer"].startswith("Да, горит")
    assert body["remaining"] == caller.MAX_TURNS - 1

    second = client.post(f"/api/operator/calls/{attempt_id}/ask", json={"question": "Какой код домофона?"}, headers=headers).json()
    assert second["turn"]["answer"] == "Не знаю"
    assert len(second["dialogue"]) == 2
    # Модель получает историю разговора и обстоятельства, а не только вопрос.
    assert echo.calls[1]["history"] == [("Что горит?", "Да, горит контейнер во дворе")]
    assert "Кировоградская" in echo.calls[1]["facts"]
    # История видна в карточке вызова.
    call = client.get(f"/api/operator/calls/{attempt_id}", headers=headers).json()
    assert [t["question"] for t in call["dialogue"]] == ["Что горит?", "Какой код домофона?"]


def test_без_модели_заявитель_молчит_и_вопрос_не_записывается(client, db_factory):
    attempt_id = make_call(db_factory)  # провайдер в тестах — заглушка
    headers = token(client, "student")
    body = client.post(f"/api/operator/calls/{attempt_id}/ask", json={"question": "Что горит?"}, headers=headers).json()
    assert body["available"] is False and body["turn"] is None and body["dialogue"] == []


def test_после_сдачи_и_после_предела_разговор_окончен(client, db_factory, monkeypatch):
    monkeypatch.setattr("app.api.operator.get_llm_provider", lambda: EchoCaller())
    attempt_id = make_call(db_factory)
    headers = token(client, "student")
    for i in range(caller.MAX_TURNS):
        assert client.post(f"/api/operator/calls/{attempt_id}/ask", json={"question": f"Вопрос {i}?"}, headers=headers).status_code == 200
    assert client.post(f"/api/operator/calls/{attempt_id}/ask", json={"question": "Ещё?"}, headers=headers).status_code == 409

    client.post(
        f"/api/operator/calls/{attempt_id}/classify",
        json={"outcome": "classify", "group": "Пожары и задымления", "path": ["на улице", "мусор", "открытое пламя"], "address": "Москва", "description": "горит"},
        headers=headers,
    )
    assert client.post(f"/api/operator/calls/{attempt_id}/ask", json={"question": "Что?"}, headers=headers).status_code == 409


@pytest.mark.parametrize("question", ["", "а"])
def test_пустой_вопрос_отклоняется(client, db_factory, question):
    attempt_id = make_call(db_factory)
    assert client.post(f"/api/operator/calls/{attempt_id}/ask", json={"question": question}, headers=token(client, "student")).status_code == 422
