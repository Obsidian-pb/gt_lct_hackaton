"""Ограничения администратора из раздела ТЗ «Роль: Администратор системы».

Проверяется каждое ограничение и — отдельно — что запрет снимается вместе
с завершением занятия. Без этой пары запрет легко сделать вечным и не
заметить: в учебном стенде занятие висит активным сутками.

Занятие в фикстуре создано сразу активным, а карточка выдана обучающемуся
«student», поэтому он и есть участник идущего занятия.
"""

from sqlalchemy import select

from app.models.training import SessionState, TrainingSession
from app.models.user import Role, User
from tests.test_api import token


def _user_id(db_factory, login: str) -> int:
    with db_factory() as db:
        return db.scalar(select(User).where(User.login == login)).id


def _finish_session(db_factory) -> None:
    """Завершает занятие из фикстуры, как это сделал бы преподаватель."""
    with db_factory() as db:
        session = db.scalar(select(TrainingSession))
        session.state = SessionState.FINISHED
        db.commit()


# --- Невмешательство в учебный процесс -------------------------------------


def test_админ_не_меняет_роль_участника_во_время_занятия(admin_client, db_factory):
    headers = token(admin_client, "root")
    student_id = _user_id(db_factory, "student")

    response = admin_client.patch(
        f"/api/admin/users/{student_id}", json={"role": str(Role.TEACHER)}, headers=headers
    )
    assert response.status_code == 409
    assert "Занятие 1" in response.json()["detail"]


def test_админ_не_меняет_службу_участника_во_время_занятия(admin_client, db_factory):
    headers = token(admin_client, "root")
    student_id = _user_id(db_factory, "student")

    response = admin_client.patch(
        f"/api/admin/users/{student_id}", json={"service_id": None}, headers=headers
    )
    assert response.status_code == 409


def test_админ_не_меняет_роль_преподавателя_идущего_занятия(admin_client, db_factory):
    headers = token(admin_client, "root")
    teacher_id = _user_id(db_factory, "teacher")

    response = admin_client.patch(
        f"/api/admin/users/{teacher_id}", json={"role": str(Role.STUDENT)}, headers=headers
    )
    assert response.status_code == 409


def test_после_завершения_занятия_роль_снова_меняется(admin_client, db_factory):
    """Ограничение действует «во время занятия», а не навсегда."""
    headers = token(admin_client, "root")
    student_id = _user_id(db_factory, "student")
    _finish_session(db_factory)

    response = admin_client.patch(
        f"/api/admin/users/{student_id}", json={"role": str(Role.TEACHER)}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["role"] == str(Role.TEACHER)


def test_запрет_не_задевает_постороннего_во_время_занятия(admin_client, db_factory):
    """Занятие идёт не у всей системы: «other» в нём не участвует."""
    headers = token(admin_client, "root")
    other_id = _user_id(db_factory, "other")

    response = admin_client.patch(
        f"/api/admin/users/{other_id}", json={"role": str(Role.TEACHER)}, headers=headers
    )
    assert response.status_code == 200


def test_повтор_прежней_роли_не_считается_вмешательством(admin_client, db_factory):
    """Значение не изменилось — значит, в учебный процесс никто не вмешался."""
    headers = token(admin_client, "root")
    student_id = _user_id(db_factory, "student")

    response = admin_client.patch(
        f"/api/admin/users/{student_id}",
        json={"role": str(Role.STUDENT), "full_name": "Иванов Иван Иванович"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Иванов Иван Иванович"


# --- Что остаётся доступным во время занятия --------------------------------


def test_админ_блокирует_нарушителя_во_время_занятия(admin_client, db_factory):
    """ТЗ вменяет администратору блокировку учётных записей как меру
    безопасности. Занятие не повод оставить нарушителя в системе."""
    headers = token(admin_client, "root")
    student_id = _user_id(db_factory, "student")

    response = admin_client.patch(
        f"/api/admin/users/{student_id}", json={"is_active": False}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_админ_меняет_пароль_во_время_занятия(admin_client, db_factory):
    headers = token(admin_client, "root")
    student_id = _user_id(db_factory, "student")

    response = admin_client.patch(
        f"/api/admin/users/{student_id}", json={"password": "Training2026"}, headers=headers
    )
    assert response.status_code == 200


def test_журнал_и_состояние_системы_доступны_во_время_занятия(admin_client):
    headers = token(admin_client, "root")
    assert admin_client.get("/api/admin/audit", headers=headers).status_code == 200
    assert admin_client.get("/api/admin/system", headers=headers).status_code == 200


def test_учётная_запись_создаётся_во_время_занятия(admin_client):
    """Новый сотрудник ни в каком занятии не участвует — мешать нечему."""
    headers = token(admin_client, "root")
    response = admin_client.post(
        "/api/admin/users",
        json={
            "login": "newcomer",
            "full_name": "Новиков Пётр Ильич",
            "password": "Training2026",
            "role": "student",
        },
        headers=headers,
    )
    assert response.status_code == 201


# --- Минимальные привилегии: работы и оценки обучающихся --------------------


def test_админ_не_читает_работу_и_оценку_обучающегося(admin_client):
    headers = token(admin_client, "root")
    assert admin_client.get("/api/attempts/1", headers=headers).status_code == 403
    assert admin_client.get("/api/attempts/1/evaluation", headers=headers).status_code == 403
    assert admin_client.get("/api/operator/calls/1", headers=headers).status_code == 403
    assert admin_client.get("/api/attempts/my", headers=headers).json() == []


def test_админ_не_меняет_оценку_через_карточку_обучающегося(admin_client):
    """Прямая формулировка ТЗ: администратор не может менять оценки."""
    headers = token(admin_client, "root")
    assert admin_client.post("/api/attempts/1/open", headers=headers).status_code == 403
    assert (
        admin_client.post(
            "/api/attempts/1/status", json={"status": "Принята"}, headers=headers
        ).status_code
        == 403
    )
    assert admin_client.post("/api/attempts/1/finish", headers=headers).status_code == 403


def test_админ_не_видит_прогресс_обучающегося(admin_client, db_factory):
    headers = token(admin_client, "root")
    student_id = _user_id(db_factory, "student")
    response = admin_client.get(
        f"/api/student/progress?student_id={student_id}", headers=headers
    )
    assert response.status_code == 403


def test_кабинет_администратора_не_отдаёт_результатов_обучения(admin_client):
    """Страховка на будущее: в ответах кабинета не должно появиться ни
    баллов, ни нарушений, ни содержимого работ — даже случайно."""
    headers = token(admin_client, "root")
    запрещённые = {"score", "violations", "criteria", "llm_summary", "evaluation", "comment"}

    users = admin_client.get("/api/admin/users", headers=headers).json()
    assert users and all(not (запрещённые & row.keys()) for row in users)

    state = admin_client.get("/api/admin/system", headers=headers).json()
    assert not (запрещённые & state.keys())
    # Сводка состояния — только счётчики, без разбивки по людям.
    assert all(not isinstance(value, (list, dict)) for value in state.values())


# --- Удаление критически важных данных --------------------------------------


def test_у_администратора_нет_необратимого_удаления(admin_client):
    """ТЗ требует резервного копирования перед удалением критичных данных.
    Резервного копирования в комплексе пока нет, поэтому в кабинете нет и
    самого удаления: учётная запись блокируется, журнал аудита не чистится.
    Тест сторожит это положение — иначе удаление появится раньше копий."""
    routes = [
        route
        for route in admin_client.app.routes
        if getattr(route, "path", "").startswith("/api/admin")
    ]
    assert routes
    assert all("DELETE" not in route.methods for route in routes)

    headers = token(admin_client, "root")
    assert admin_client.delete("/api/admin/users/1", headers=headers).status_code == 405
