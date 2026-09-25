"""Черновик карточки оператора: сохраняется без оценки, восстанавливается при открытии."""

from tests.test_operator_api import make_call, token

CARD = {
    "outcome": "classify",
    "group": "Пожары и задымления",
    "path": ["на улице", "мусор"],
    "address": "Москва, ул. Кировоградская",
    "description": "горит",
    "caller_phone": "916",
    "address_parts": {"subject": "Москва", "house": ""},
    "flags": ["пострадавшие"],
}


def test_черновик_сохраняется_и_виден_в_карточке_без_оценки(client, db_factory):
    attempt_id = make_call(db_factory)
    headers = token(client, "student")
    saved = client.put(f"/api/operator/calls/{attempt_id}/draft", json=CARD, headers=headers)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["finished"] is False
    assert body["chosen_group"] == CARD["group"] and body["chosen_path"] == CARD["path"]
    assert body["entered_address_parts"] == {"subject": "Москва"}  # пустое значение не хранится
    assert body["chosen_flags"] == ["пострадавшие"]
    # Повторное открытие отдаёт то же самое, оценки при этом нет.
    again = client.get(f"/api/operator/calls/{attempt_id}", headers=headers).json()
    assert again["entered_description"] == "горит" and again["finished"] is False


def test_черновик_после_сдачи_невозможен(client, db_factory):
    attempt_id = make_call(db_factory)
    headers = token(client, "student")
    client.post(f"/api/operator/calls/{attempt_id}/classify", json={**CARD, "path": ["на улице", "мусор", "открытое пламя"]}, headers=headers)
    assert client.put(f"/api/operator/calls/{attempt_id}/draft", json=CARD, headers=headers).status_code == 409


def test_черновик_проверяет_ключи_признаков(client, db_factory):
    attempt_id = make_call(db_factory)
    response = client.put(
        f"/api/operator/calls/{attempt_id}/draft",
        json={**CARD, "flags": ["опечатка"]},
        headers=token(client, "student"),
    )
    assert response.status_code == 422

