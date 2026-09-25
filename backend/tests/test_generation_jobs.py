"""Формирование карточек в фоне: задание, ход, результат."""

from app.models.user import DispatchService
from tests.test_api import token

GROUP = "Пожары и задымления"


def _service_id(db_factory) -> int:
    with db_factory() as db:
        return db.query(DispatchService).first().id


def test_кнопка_возвращает_задание_а_карточки_появляются_после(client, db_factory):
    headers = token(client, "teacher")
    before = len(client.get("/api/teacher/scenarios", headers=headers).json())

    response = client.post(
        "/api/teacher/scenarios/generate",
        json={"group": GROUP, "count": 2, "difficulty": 2, "service_id": _service_id(db_factory)},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["requested"] == 2 and job["state"] in ("running", "done")

    # В тестовом клиенте фоновая задача выполняется до возврата ответа,
    # поэтому следующий запрос уже видит итог.
    status = client.get(f"/api/teacher/scenarios/generate/{job['id']}", headers=headers).json()
    assert status["state"] == "done", status
    assert status["finished"] == 2
    assert status["created"] == len(status["scenario_ids"])
    after = client.get("/api/teacher/scenarios", headers=headers).json()
    assert len(after) == before + status["created"]
    assert client.get("/api/teacher/scenarios/generate/active", headers=headers).json() == []


def test_несуществующее_задание(client):
    headers = token(client, "teacher")
    assert client.get("/api/teacher/scenarios/generate/999999", headers=headers).status_code == 404


def test_неизвестная_служба(client):
    headers = token(client, "teacher")
    response = client.post(
        "/api/teacher/scenarios/generate",
        json={"group": GROUP, "count": 1, "difficulty": 1, "service_id": 999_999},
        headers=headers,
    )
    assert response.status_code == 404
