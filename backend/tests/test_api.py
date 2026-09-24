"""Сквозная проверка API: вход, работа с карточкой, получение оценки."""

import pytest
from fastapi.testclient import TestClient

from app.api.attempts import run_llm_review
from app.llm.base import CommentReview
from app.services.response_status import ResponseStatus as S


def token(client: TestClient, login: str) -> dict:
    response = client.post("/api/auth/token", data={"username": login, "password": "pwd"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_здоровье_сервиса(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["ekp_rules"] == 1283


def test_вход_с_неверным_паролем_отклоняется(client):
    response = client.post("/api/auth/token", data={"username": "student", "password": "nope"})
    assert response.status_code == 401


def test_без_токена_доступа_нет(client):
    assert client.get("/api/attempts/my").status_code == 401


def test_карточка_содержит_список_оповещения_из_екп(client):
    headers = token(client, "student")
    cards = client.get("/api/attempts/my", headers=headers).json()
    assert len(cards) == 1
    card = cards[0]
    assert card["address"].startswith("Москва, ул. Берзарина")
    assert card["available_statuses"] == [str(S.ACCEPTED), str(S.REJECTED)]
    assert "МЧС" in card["notified_services"]
    # Список приходит с обоснованием: оповещённые повторяют список,
    # неоповещённые подсказывают признак, которого не хватило.
    reasons = card["notification_reasons"]
    assert [r["service"] for r in reasons if r["notified"]] == list(card["notified_services"])
    assert all(r["reason"] for r in reasons)
    assert any(not r["notified"] and "только при признаке" in r["reason"] for r in reasons)


def test_обучающийся_не_видит_чужую_карточку(client):
    headers = token(client, "other")
    assert client.get("/api/attempts/my", headers=headers).json() == []
    assert client.get("/api/attempts/1", headers=headers).status_code == 403


def test_недопустимый_статус_отклоняется(client):
    headers = token(client, "student")
    response = client.post(
        "/api/attempts/1/status", json={"status": str(S.ARRIVED)}, headers=headers
    )
    assert response.status_code == 409
    assert "нельзя перейти" in response.json()["detail"]


def test_неизвестный_статус_отклоняется(client):
    headers = token(client, "student")
    response = client.post("/api/attempts/1/status", json={"status": "Съел"}, headers=headers)
    assert response.status_code == 422


def test_полный_цикл_обработки_карточки(client):
    headers = token(client, "student")
    client.post("/api/attempts/1/open", headers=headers)

    card = client.post(
        "/api/attempts/1/status",
        json={
            "status": str(S.REJECTED),
            "comment": "Не обслуживаем, информация передана в диспетчерскую «Практика»",
        },
        headers=headers,
    ).json()
    assert card["current_status"] == str(S.REJECTED)
    assert card["available_statuses"] == [str(S.ACCEPTED)]

    evaluation = client.post("/api/attempts/1/finish", headers=headers).json()
    assert evaluation["violations"] == []
    assert evaluation["score"] == 1.0
    # Детерминированная часть готова сразу, смысловая проверка ещё идёт.
    assert evaluation["llm_pending"] is True


@pytest.mark.asyncio
async def test_фоновая_оценка_дописывает_пропущенный_пункт_и_идемпотентна(client, monkeypatch):
    class FakeProvider:
        name = "fake"

        async def review_comment(self, *, comment, required_points, context):
            return CommentReview(
                missing_points=list(required_points), summary="проверено", available=True
            )

    monkeypatch.setattr("app.api.attempts.get_llm_provider", lambda: FakeProvider())
    headers = token(client, "student")
    client.post(
        "/api/attempts/1/status",
        json={"status": str(S.REJECTED), "comment": "Не обслуживаем"},
        headers=headers,
    )
    client.post("/api/attempts/1/finish", headers=headers)

    await run_llm_review(1)

    evaluation = client.get("/api/attempts/1/evaluation", headers=headers).json()
    assert evaluation["llm_pending"] is False
    assert [v["code"] for v in evaluation["violations"]] == ["V5"]
    assert "Практика" in evaluation["violations"][0]["detail"]
    assert evaluation["score"] < 1.0
