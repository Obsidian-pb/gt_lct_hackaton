"""Контрактные REST-тесты ИИ-микросервиса.

Используют фиктивный провайдер (подменяется get_provider в роутере);
сеть и ключи не требуются. Проверяют Bearer-токен, статусы ошибок и
stateless-операции ядра через HTTP.
"""
from __future__ import annotations

import copy
import os

os.environ["AI_SERVICE_TOKEN"] = "test-token"
os.environ["AI_PROVIDER"] = ""
os.environ["AI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.ai import card_factory  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class StubProvider:
    model = "stub-model"

    def __init__(self, responses: list[dict] | None = None, default=None):
        self.responses = list(responses or [])
        self.default = default or {}
        self.calls: list[dict] = []

    def generate(self, system, payload, temperature=0.3, schema=None):
        self.calls.append({"system": system, "payload": payload, "schema": schema})
        if self.responses:
            return self.responses.pop(0)
        return copy.deepcopy(self.default)

    def status(self):
        return {
            "state": "available", "message": "OK", "provider": "stub",
            "model": self.model, "model_selected": True, "scope_detected": False,
        }


@pytest.fixture()
def stub_provider(monkeypatch):
    provider = StubProvider(default={
        "title": "Пожар на балконе", "report": "Горит балкон.",
        "fields": {k: "Неизвестно" for k in card_factory.GENERATED},
    })
    monkeypatch.setattr("app.api.routes.get_provider", lambda: provider)
    return provider


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
        "title": "Пожар на балконе", "report": "Здравствуйте, горит балкон на улице Лесной, дом 7.",
        "fields": fields, "class_ids": [catalog["id"]], "services": list(catalog["services"]),
        "main_service": catalog["main_service"], "flags": {"injured": "unknown"},
    }


client = TestClient(app)


def test_health_is_public() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_operations_require_token() -> None:
    resp = client.post("/api/v1/ai/checks")
    assert resp.status_code == 401
    resp = client.post("/api/v1/cards/generations", json={"topic": "пожар"})
    assert resp.status_code == 401


def test_ai_checks_with_token(stub_provider) -> None:
    resp = client.post("/api/v1/ai/checks", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "available"
    assert body["model"] == "stub-model"


def test_cards_generations(stub_provider) -> None:
    payload = {
        "topic": "пожар на балконе", "index": 1, "total": 1,
        "incident_class": {"id": "custom-1", "title": "Пожар", "services": ["101"], "main_service": "101"},
    }
    resp = client.post("/api/v1/cards/generations", json=payload, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["content"]["class_ids"] == ["custom-1"]
    assert body["prompt_version"] == "cards-v2.0"


def test_cards_generations_bad_request_422() -> None:
    resp = client.post("/api/v1/cards/generations", json={"topic": "x", "category": "unknown"}, headers=AUTH)
    assert resp.status_code == 422


def test_cards_validations_ok(stub_provider) -> None:
    resp = client.post("/api/v1/cards/validations", json={"content": sample_content()}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_cards_validations_bad_422(stub_provider) -> None:
    resp = client.post("/api/v1/cards/validations", json={"content": {"bad": "structure"}}, headers=AUTH)
    assert resp.status_code == 422


def test_cards_caller_replies(stub_provider) -> None:
    scenario = {"version": 1, "phone_callback": "+7 (000) 123-45-67"}
    stub_provider.default = {"reply": "Горит балкон, дом 7.", "callback_requested": False}
    payload = {"content": sample_content(), "caller_scenario": scenario, "question": "Что горит?", "turns": []}
    resp = client.post("/api/v1/cards/caller-replies", json=payload, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["callback_disclosed"] is False
    assert body["prompt_version"].startswith("card-caller")


def test_cards_service_replies(stub_provider) -> None:
    stub_provider.default = {"reply": "Повторите адрес"}
    payload = {
        "service": {"name": "ПС-1", "role": "диспетчер"},
        "persona": "строгий", "level": "hard", "history": [], "question": "дом 7",
        "mode": "clear", "attempt": 1,
    }
    resp = client.post("/api/v1/cards/service-replies", json=payload, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["reply"] == "Повторите адрес"


def test_cards_service_replies_drop(stub_provider) -> None:
    payload = {
        "service": {"name": "ПС-1", "role": "диспетчер"},
        "question": "Принимайте карточку", "mode": "drop", "attempt": 1,
    }
    resp = client.post("/api/v1/cards/service-replies", json=payload, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivered"] == ""
    assert not stub_provider.calls


def test_assessments(stub_provider) -> None:
    history = [
        {"role": "dispatcher", "text": "Что случилось?"},
        {"role": "caller", "text": "Горит балкон, дом 7 по Лесной."},
    ]
    verdict_row = {"verdict": "correct", "comment": "Совпадает",
                   "evidence": [{"turn_id": 2, "quote": "Горит балкон, дом 7 по Лесной."}], "clarification": ""}
    stub_provider.default = {"summary": "Хорошо", "fields": {"street": verdict_row, "house": verdict_row}}
    payload = {
        "labels": {"street": "Улица", "house": "Дом"},
        "card": {"street": "Лесная", "house": "7"},
        "expected": {"street": "Лесная", "house": "7"},
        "history": history, "hints_used": 0,
    }
    resp = client.post("/api/v1/assessments", json=payload, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["score"] == 100.0
    assert body["fields"]["street"]["evidence"][0]["turn_id"] == 2


def test_metadata_public_contract() -> None:
    resp = client.get("/api/v1/metadata", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert "groups" in body and "catalog" in body and "flags" in body