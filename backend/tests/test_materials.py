"""Справочная база: кто что видит, кто что правит и какие файлы принимаются."""

from app.api.materials import MAX_FILE_BYTES
from tests.test_api import token

# Байты нарочно не ASCII: проверка обязана показать, что файл доходит
# до обучающегося без перекодировки.
PDF = "%PDF-1.4\n1 0 obj\nучебная методичка\n".encode()


def create_material(client, headers, **fields) -> int:
    payload = {"title": "Памятка по приёму вызова", "summary": "Кратко", "body": "Текст"}
    payload.update(fields)
    response = client.post("/api/materials", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_черновик_не_виден_обучающемуся(client):
    teacher = token(client, "teacher")
    student = token(client, "student")
    material_id = create_material(client, teacher)

    assert client.get("/api/materials", headers=student).json() == []
    assert client.get(f"/api/materials/{material_id}", headers=student).status_code == 404
    # Автору собственный черновик виден — иначе его нельзя было бы дописать.
    assert len(client.get("/api/materials", headers=teacher).json()) == 1


def test_опубликованный_материал_виден_обучающемуся(client):
    teacher = token(client, "teacher")
    student = token(client, "student")
    material_id = create_material(client, teacher, body="Как принимать вызов")
    published = client.post(f"/api/materials/{material_id}/publish", headers=teacher)
    assert published.status_code == 200

    listed = client.get("/api/materials", headers=student).json()
    assert [m["id"] for m in listed] == [material_id]
    assert listed[0]["is_mine"] is False

    detail = client.get(f"/api/materials/{material_id}", headers=student).json()
    assert detail["body"] == "Как принимать вызов"
    assert detail["author_name"] == "Преподаватель"


def test_снятый_с_публикации_материал_снова_скрыт(client):
    teacher = token(client, "teacher")
    student = token(client, "student")
    material_id = create_material(client, teacher)
    client.post(f"/api/materials/{material_id}/publish", headers=teacher)
    client.post(f"/api/materials/{material_id}/unpublish", headers=teacher)

    assert client.get(f"/api/materials/{material_id}", headers=student).status_code == 404


def test_пустой_материал_не_публикуется(client):
    teacher = token(client, "teacher")
    material_id = create_material(client, teacher, body=None)
    response = client.post(f"/api/materials/{material_id}/publish", headers=teacher)
    assert response.status_code == 409


def test_обучающийся_не_создаёт_и_не_изменяет_материалы(client):
    teacher = token(client, "teacher")
    student = token(client, "student")
    material_id = create_material(client, teacher)
    client.post(f"/api/materials/{material_id}/publish", headers=teacher)

    created = client.post(
        "/api/materials", json={"title": "Своя методичка"}, headers=student
    )
    edited = client.patch(
        f"/api/materials/{material_id}", json={"title": "Правка"}, headers=student
    )
    removed = client.delete(f"/api/materials/{material_id}", headers=student)
    hidden = client.post(f"/api/materials/{material_id}/unpublish", headers=student)
    assert [r.status_code for r in (created, edited, removed, hidden)] == [403, 403, 403, 403]


def test_правка_заголовка_не_стирает_текст(client):
    teacher = token(client, "teacher")
    material_id = create_material(client, teacher, body="Исходный текст")
    updated = client.patch(
        f"/api/materials/{material_id}", json={"title": "Новый заголовок"}, headers=teacher
    ).json()
    assert updated["title"] == "Новый заголовок"
    assert updated["body"] == "Исходный текст"


def test_загруженный_файл_скачивается_теми_же_байтами(client):
    teacher = token(client, "teacher")
    student = token(client, "student")
    material_id = create_material(client, teacher)

    uploaded = client.post(
        f"/api/materials/{material_id}/file",
        files={"file": ("Инструкция оператора.pdf", PDF, "application/pdf")},
        headers=teacher,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["size_bytes"] == len(PDF)
    assert uploaded.json()["file_name"] == "Инструкция оператора.pdf"

    client.post(f"/api/materials/{material_id}/publish", headers=teacher)
    downloaded = client.get(f"/api/materials/{material_id}/file", headers=student)
    assert downloaded.status_code == 200
    assert downloaded.content == PDF
    assert downloaded.headers["content-type"] == "application/pdf"
    # Русское имя уходит в filename* — кириллица в filename= ломается в браузерах.
    assert "filename*=UTF-8''" in downloaded.headers["content-disposition"]


def test_файл_черновика_не_скачивается_обучающимся(client):
    teacher = token(client, "teacher")
    student = token(client, "student")
    material_id = create_material(client, teacher)
    client.post(
        f"/api/materials/{material_id}/file",
        files={"file": ("методичка.pdf", PDF, "application/pdf")},
        headers=teacher,
    )
    assert client.get(f"/api/materials/{material_id}/file", headers=student).status_code == 404


def test_слишком_большой_файл_отклоняется(client):
    teacher = token(client, "teacher")
    material_id = create_material(client, teacher)
    too_big = b"\x00" * (MAX_FILE_BYTES + 1)
    response = client.post(
        f"/api/materials/{material_id}/file",
        files={"file": ("огромная.pdf", too_big, "application/pdf")},
        headers=teacher,
    )
    assert response.status_code == 413
    # Отказ не должен оставить в базе половину файла.
    stored = client.get(f"/api/materials/{material_id}", headers=teacher).json()
    assert stored["file_name"] is None and stored["size_bytes"] is None


def test_недопустимый_тип_файла_отклоняется(client):
    teacher = token(client, "teacher")
    material_id = create_material(client, teacher)
    response = client.post(
        f"/api/materials/{material_id}/file",
        files={"file": ("script.exe", b"MZ\x90\x00", "application/x-msdownload")},
        headers=teacher,
    )
    assert response.status_code == 415

    # Расширение сверяется с заявленным типом: «.exe» под видом PDF не проходит.
    disguised = client.post(
        f"/api/materials/{material_id}/file",
        files={"file": ("script.exe", b"MZ\x90\x00", "application/pdf")},
        headers=teacher,
    )
    assert disguised.status_code == 415


def test_чужой_материал_преподавателю_не_принадлежит(client, db_factory):
    """Правит только автор: под методичкой стоит его имя, и отвечает за неё он."""
    from app.core.security import hash_password
    from app.models.user import Role, User

    with db_factory() as db:
        db.add(
            User(
                login="teacher2",
                full_name="Второй преподаватель",
                hashed_password=hash_password("pwd"),
                role=Role.TEACHER,
            )
        )
        db.commit()

    author = token(client, "teacher")
    other = token(client, "teacher2")
    material_id = create_material(client, author)
    client.post(f"/api/materials/{material_id}/publish", headers=author)

    assert client.patch(
        f"/api/materials/{material_id}", json={"title": "Чужая правка"}, headers=other
    ).status_code == 403
    assert client.delete(f"/api/materials/{material_id}", headers=other).status_code == 403
    # Читать опубликованное чужое, разумеется, можно.
    assert client.get(f"/api/materials/{material_id}", headers=other).status_code == 200


def test_удаление_материала(client):
    teacher = token(client, "teacher")
    material_id = create_material(client, teacher)
    assert client.delete(f"/api/materials/{material_id}", headers=teacher).status_code == 204
    assert client.get(f"/api/materials/{material_id}", headers=teacher).status_code == 404
