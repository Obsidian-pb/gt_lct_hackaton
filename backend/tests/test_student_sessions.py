"""Сводка занятий для обучающегося: инструктаж до первого вызова и итог после."""

from tests.test_api import token


def test_обучающийся_видит_свои_занятия(client):
    headers = token(client, "student")
    response = client.get("/api/student/sessions", headers=headers)
    assert response.status_code == 200, response.text
    sessions = response.json()
    assert sessions, "у учебного обучающегося есть идущее занятие из сида"
    first = sessions[0]
    for key in (
        "title", "mode", "state", "teacher_name", "pickup_deadline_seconds",
        "handling_deadline_seconds", "pass_score", "cards_total", "cards_issued",
        "cards_done", "next_issue_in_seconds", "average_score", "critical", "passed",
    ):
        assert key in first, key
    assert first["cards_total"] >= first["cards_issued"] >= first["cards_done"]
    # Ни одной работы не завершено — судить о зачёте не по чему.
    if first["cards_done"] == 0:
        assert first["passed"] is None


def test_идущие_занятия_идут_первыми(client):
    sessions = client.get("/api/student/sessions", headers=token(client, "student")).json()
    states = [s["state"] for s in sessions]
    if "finished" in states and "active" in states:
        assert states.index("active") < states.index("finished")


def test_преподавателю_раздел_закрыт(client):
    assert client.get("/api/student/sessions", headers=token(client, "teacher")).status_code == 403
