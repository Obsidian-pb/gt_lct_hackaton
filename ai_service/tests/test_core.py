"""Unit-тесты ИИ-ядра с фиктивным провайдером (без сети и ключа).

Перенесены из backend_new/tests/test_ai_core.py при выносе ядра в микросервис.
"""
import copy
import json

import pytest

from app.services.ai import card_caller, card_factory, card_reference, dds
from app.services.ai import ai_core


class StubProvider:
    """Возвращает заранее заданный ответ или последнюю заготовку по промпту."""

    def __init__(self, responses: list[dict] | None = None, default=None):
        self.model = "stub-model"
        self.responses = list(responses or [])
        self.default = default or {}
        self.calls: list[dict] = []

    def generate(self, system, payload, temperature=0.3, schema=None):
        self.calls.append({"system": system, "payload": payload, "schema": schema})
        if self.responses:
            return self.responses.pop(0)
        return copy.deepcopy(self.default)


def sample_content() -> dict:
    catalog = card_factory.CATALOG[0]
    fields = {k: "" for k in card_factory.LABELS}
    fields.update({
        "caller_name": "Иванов Иван", "caller_role": "Очевидец",
        "phone_callback": "Не указан", "country": "Неизвестно", "city": "Учебный город",
        "street": "Лесная", "house": "7", "description": "Возгорание на балконе",
        "people": "Неизвестно", "injured": "Неизвестно", "floors": "9",
    })
    return {
        "title": "Пожар на балконе", "report": "Здравствуйте, горит балкон на улице Лесной, дом 7. Я сосед, не знаю, есть ли кто-то внутри.",
        "fields": fields, "class_ids": [catalog["id"]], "services": list(catalog["services"]),
        "main_service": catalog["main_service"], "flags": {"injured": "unknown"},
    }


# --- card_factory -----------------------------------------------------------------

def test_validate_content_accepts_sample() -> None:
    content = card_factory.validate_content(sample_content())
    assert content["title"] == "Пожар на балконе"
    assert set(content["fields"]) == set(card_factory.LABELS)


def test_validate_content_rejects_bad_flag() -> None:
    bad = sample_content()
    bad["flags"] = {"injured": "maybe"}
    with pytest.raises(ValueError, match="признак"):
        card_factory.validate_content(bad)


def test_validate_content_rejects_wrong_coords() -> None:
    bad = sample_content()
    bad["fields"]["latitude"] = "99"
    bad["fields"]["longitude"] = "99"
    with pytest.raises(ValueError, match="координат"):
        card_factory.validate_content(bad)


def test_generate_with_explicit_incident_class() -> None:
    provider = StubProvider(default={
        "title": "Пожар на балконе", "report": "Горит балкон.",
        "fields": {k: "Неизвестно" for k in card_factory.GENERATED},
    })
    request = {
        "topic": "пожар на балконе", "total": 1, "index": 1,
        "incident_class": {"id": "custom-1", "title": "Пожар", "services": ["101"], "main_service": "101"},
    }
    result = card_factory.generate(provider, request)
    assert result["content"]["fields"]["city"] == "Неизвестно"
    assert "incident_class" in provider.calls[0]["payload"]
    assert result["content"]["class_ids"] == ["custom-1"]


def test_generate_requires_valid_options() -> None:
    provider = StubProvider()
    with pytest.raises(ValueError, match="классификатора"):
        card_factory.generate(provider, {"topic": "x", "category": "unknown"})


# --- card_caller ------------------------------------------------------------------

def _scenario() -> dict:
    return {"version": 1, "phone_callback": "+7 (000) 123-45-67"}


def test_caller_ask_returns_reply() -> None:
    provider = StubProvider(default={"reply": "Горит балкон, дом 7.", "callback_requested": False})
    result = card_caller.ask(provider, {"content": sample_content(), "caller_scenario": _scenario(),
                                        "question": "Что горит?", "turns": []})
    assert "горит" in result["reply"].lower()
    assert result["callback_disclosed"] is False


def test_caller_callback_injects_scenario_phone() -> None:
    provider = StubProvider(default={"reply": "Перезвоните на другой номер", "callback_requested": True})
    result = card_caller.ask(provider, {"content": sample_content(), "caller_scenario": _scenario(),
                                        "question": "Куда перезвонить?", "turns": []})
    assert "+7 (000) 123-45-67" in result["reply"]


def test_caller_rejects_invented_digits() -> None:
    provider = StubProvider(default={"reply": "Звоните 8 999 111-22-33", "callback_requested": False})
    with pytest.raises(ValueError, match="телефон"):
        card_caller.ask(provider, {"content": sample_content(), "caller_scenario": _scenario(),
                                   "question": "Куда перезвонить?", "turns": []})


def test_caller_rejects_odd_turns() -> None:
    provider = StubProvider()
    with pytest.raises(ValueError, match="история"):
        card_caller.ask(provider, {"content": sample_content(), "caller_scenario": _scenario(),
                                   "question": "Адрес?", "turns": [{"role": "dispatcher", "text": "Вопрос"}]})


# --- card_reference ---------------------------------------------------------------

def test_reference_generate_binds_quotes() -> None:
    content = sample_content()
    answer = {
        "expected_fields": {k: {"value": "Неизвестно", "source_id": 0} for k in card_factory.GENERATED},
        "summary": "Пример", "classification_reason": "Пожар", "services_reason": "Пожарная охрана",
        "questions": ["Есть ли люди?"], "critical_errors": ["Не уточнено наличие людей"],
    }
    answer["expected_fields"]["street"] = {"value": "Лесная", "source_id": 1}
    provider = StubProvider(default=answer)
    result = card_reference.generate(provider, {"content": content})
    assert result["answer"]["expected_fields"]["street"]["evidence"].startswith("Здравствуйте")
    assert card_reference.validate_reference(result, content)["answer"]["summary"] == "Пример"


# --- ai_core ----------------------------------------------------------------------

def test_assess_card_score_and_evidence() -> None:
    history = [
        {"role": "dispatcher", "text": "Что случилось?"},
        {"role": "caller", "text": "Горит балкон, дом 7 по Лесной."},
        {"role": "dispatcher", "text": "Кто-то внутри?"},
        {"role": "caller", "text": "Не знаю."},
    ]
    verdict_row = {"verdict": "correct", "comment": "Совпадает", "evidence": [{"turn_id": 2, "quote": "Горит балкон, дом 7 по Лесной."}], "clarification": ""}
    provider = StubProvider(default={"summary": "Хорошо", "fields": {
        "street": verdict_row, "house": verdict_row, "people": {**verdict_row, "verdict": "partial"},
    }})
    assessment = ai_core.assess_card(
        provider, labels={"street": "Улица", "house": "Дом", "people": "Люди"},
        card={"street": "Лесная", "house": "7", "people": ""},
        expected={"street": "Лесная", "house": "7", "people": "Неизвестно"},
        history=history,
    )
    assert assessment["score"] == round((1.0 + 1.0 + 0.5) / 3 * 100, 2)
    assert assessment["fields"]["street"]["evidence"][0]["turn_id"] == 2


def test_assess_card_flags_invented_citation() -> None:
    row = {"verdict": "correct", "comment": "ок", "evidence": [{"turn_id": 1, "quote": "Такой цитаты нет"}], "clarification": ""}
    provider = StubProvider(default={"summary": "s", "fields": {"street": row}})
    assessment = ai_core.assess_card(
        provider, labels={"street": "Улица"}, card={"street": "x"},
        expected={"street": "y"}, history=[{"role": "caller", "text": "Привет"}],
    )
    assert assessment["fields"]["street"]["evidence"] == []
    assert assessment["fields"]["street"]["citation_warning"] is True


def test_difficulty_mapping() -> None:
    assert ai_core.difficulty_to_level(1) == "easy"
    assert ai_core.difficulty_to_level(3) == "medium"
    assert ai_core.difficulty_to_level(5) == "hard"


# --- dds --------------------------------------------------------------------------

def test_dds_deliver_modes() -> None:
    assert dds.deliver("один два три", "clear") == "один два три"
    assert dds.deliver("один два три", "partial") == "один"
    assert dds.deliver("один два три", "drop") == ""


def test_dds_service_reply_drop_no_ai_call() -> None:
    provider = StubProvider()
    reply, delivered = dds.service_reply(provider, service={"name": "ПС-1", "role": "диспетчер"},
                                         persona="спокойный", level="medium",
                                         history=[], question="Принимайте карточку", mode="drop", attempt=1)
    assert delivered == ""
    assert "оборвалась" in reply
    assert not provider.calls


def test_dds_service_reply_partial_uses_delivered_only() -> None:
    provider = StubProvider(default={"reply": "Повторите адрес"})
    history = [{"role": "dispatcher", "text": "адрес Лесная 7", "delivered": "адрес Лесная"},
               {"role": "service", "text": "Пожарная охрана, слушаю."}]
    reply, delivered = dds.service_reply(provider, service={"name": "ПС-1", "role": "диспетчер"},
                                         persona="строгий", level="hard", history=history,
                                         question="дом 7", mode="partial", attempt=1)
    assert delivered == "дом"
    sent = provider.calls[0]["payload"]
    assert "дом 7" not in json.dumps(sent["history"], ensure_ascii=False)
    assert sent["delivered_message"] == "дом"