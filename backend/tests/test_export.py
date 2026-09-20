"""Выгрузка отчёта преподавателя в CSV и PDF."""

import base64
import csv
import io
import re
import zlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.models.training import (
    Attempt,
    Evaluation,
    Scenario,
    SessionState,
    StatusEvent,
    TrainingSession,
)
from app.models.user import User
from app.services import export
from app.services.response_status import ResponseStatus as S

ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"


def token(client: TestClient, login: str) -> dict:
    response = client.post("/api/auth/token", data={"username": login, "password": "pwd"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def violation(code: str) -> dict:
    return {"code": code, "title": "", "severity": "", "detail": "", "example": ""}


@pytest.fixture
def filled(db_factory):
    """Занятие с результатами двух обучающихся.

    Числа подобраны так, чтобы в выгрузке их можно было сверить вручную:
    у Иванова три карточки (одна не завершена) и средний балл 80, у Петрова
    две карточки с баллом 50 и обе взяты с опозданием.
    """
    with db_factory() as db:
        session = db.query(TrainingSession).first()
        scenario = db.query(Scenario).first()
        ivanov = db.query(User).filter_by(login="student").one()
        petrov = db.query(User).filter_by(login="other").one()
        started = datetime.now(timezone.utc) - timedelta(hours=1)
        session.students = [ivanov, petrov]
        session.state = SessionState.FINISHED
        session.started_at = started
        session.finished_at = started + timedelta(minutes=40)

        # (обучающийся, балл, секунды до взятия в работу, коды нарушений, грамматика)
        plan = [
            (ivanov, 0.9, 10.0, [], []),
            (ivanov, 0.7, 45.0, ["V8", "V4"], ["адресс", "позваните"]),
            (petrov, 0.5, 50.0, ["V8"], []),
            (petrov, 0.5, 55.0, ["V8", "V4"], []),
        ]
        for number, (student, score, elapsed, codes, grammar) in enumerate(plan):
            attempt = Attempt(
                session=session,
                student=student,
                scenario=scenario,
                issued_at=started + timedelta(minutes=number),
                opened_at=started + timedelta(minutes=number, seconds=elapsed),
                finished_at=started + timedelta(minutes=number, seconds=elapsed + 60),
            )
            attempt.events.append(
                StatusEvent(status=str(S.ACCEPTED), comment=None, elapsed_seconds=elapsed)
            )
            attempt.evaluation = Evaluation(
                score=score,
                criteria={},
                violations=[violation(code) for code in codes],
                grammar_issues=grammar,
                llm_pending=False,
            )
            db.add(attempt)
        db.commit()
    return db_factory


def rows(payload: bytes) -> list[list[str]]:
    """Разбирает выгрузку так же, как её прочитает Excel."""
    assert payload.startswith(b"\xef\xbb\xbf"), "Excel на Windows ждёт BOM"
    text = payload.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text), delimiter=";"))


def find(table: list[list[str]], first: str) -> list[str]:
    return next(row for row in table if row and row[0] == first)


def pdf_streams(data: bytes) -> list[bytes]:
    """Распакованное содержимое всех потоков документа."""
    out = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = match.group(1)
        for decode in (
            lambda r: zlib.decompress(r),
            lambda r: zlib.decompress(base64.a85decode(r.strip(), adobe=True)),
        ):
            try:
                out.append(decode(raw))
            except Exception:
                continue
            break
    return out


def pdf_text(data: bytes) -> str:
    """Текст документа — тем же путём, каким его читает просмотрщик.

    Байты в потоке страницы — номера глифов встроенного подмножества шрифта,
    в человеческий текст их переводит карта ToUnicode. Все символы отчёта
    укладываются в одно подмножество, поэтому карта в документе одна.
    """
    streams = pdf_streams(data)
    unicode_map: dict[int, str] = {}
    for stream in streams:
        if b"beginbfchar" not in stream:
            continue
        for code, point in re.findall(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4})>", stream):
            unicode_map[int(code, 16)] = chr(int(point, 16))

    pieces = []
    for stream in streams:
        if b"BT" not in stream or b"Tf" not in stream or stream.startswith(b"\x00\x01"):
            continue
        for chunk in pdf_strings(stream):
            pieces.append("".join(unicode_map.get(byte, chr(byte)) for byte in chunk))
    return " ".join(pieces)


def pdf_strings(stream: bytes) -> list[bytes]:
    """Строковые литералы потока страницы: всё, что заключено в скобки."""
    found: list[bytes] = []
    position = 0
    while position < len(stream):
        if stream[position] != 0x28:  # (
            position += 1
            continue
        position += 1
        buffer = bytearray()
        depth = 1
        while position < len(stream):
            char = stream[position]
            if char == 0x5C:  # обратная косая: экранирование
                tail = stream[position + 1 : position + 4]
                digits = bytes(c for c in tail if 0x30 <= c <= 0x37)
                if digits and tail[:1] == digits[:1]:
                    buffer.append(int(digits, 8) & 0xFF)
                    position += 1 + len(digits)
                else:
                    buffer += stream[position + 1 : position + 2]
                    position += 2
                continue
            if char == 0x28:
                depth += 1
            elif char == 0x29:  # )
                depth -= 1
                if depth == 0:
                    position += 1
                    break
            buffer.append(char)
            position += 1
        found.append(bytes(buffer))
    return found


def test_выгрузка_содержит_результаты_обучающихся(client, filled):
    response = client.get(
        "/api/teacher/sessions/1/report.csv", headers=token(client, "teacher")
    )
    assert response.status_code == 200
    table = rows(response.content)

    # Карточек, завершено, средний балл, просрочек, нарушений.
    assert find(table, "Иванов И.И.")[1:] == ["3", "2", "80,0", "1", "2"]
    assert find(table, "Петров П.П.")[1:] == ["2", "2", "50,0", "2", "3"]


def test_выгрузка_содержит_итоги_занятия(client, filled):
    table = rows(
        client.get(
            "/api/teacher/sessions/1/report.csv", headers=token(client, "teacher")
        ).content
    )

    assert find(table, "Занятие")[1] == "Занятие 1"
    assert find(table, "Режим обучения")[1] == "Диспетчер ДДС"
    assert find(table, "Карточек выдано")[1] == "5"
    assert find(table, "Карточек завершено")[1] == "4"
    assert find(table, "Средний балл")[1] == "65,0"
    assert find(table, "Среднее время до взятия в работу, с")[1] == "40,0"
    assert find(table, "Доля просрочек норматива, %")[1] == "75,0"
    assert find(table, "Замечаний к грамматике")[1] == "2"
    # V8 встретилось трижды на четырёх завершённых карточках.
    assert find(table, "V8")[3:] == ["3", "75,0"]
    assert any("Норматив взятия в работу" in row[0] for row in table if row)


def test_незавершённое_занятие_выгружается_без_ошибки(client):
    """Карточки выданы, оценок ещё нет — выгрузка всё равно должна открыться."""
    headers = token(client, "teacher")
    table = rows(client.get("/api/teacher/sessions/1/report.csv", headers=headers).content)
    assert find(table, "Карточек завершено")[1] == "0"
    assert find(table, "Средний балл")[1] == "—"

    # Ни нарушений, ни баллов: таблицы пустые, документ всё равно собирается.
    pdf = client.get("/api/teacher/sessions/1/report.pdf", headers=headers)
    assert pdf.status_code == 200
    assert "ни одна карточка не завершена" in pdf_text(pdf.content)


def test_числа_записаны_с_десятичной_запятой(client, filled):
    """Русская локаль Excel читает «80.0» как текст, а не как число."""
    payload = client.get(
        "/api/teacher/sessions/1/report.csv", headers=token(client, "teacher")
    ).content
    assert "80,0" in payload.decode("utf-8-sig")
    assert "80.0" not in payload.decode("utf-8-sig")


def test_csv_отдаётся_файлом_с_латинским_именем(client, filled):
    response = client.get(
        "/api/teacher/sessions/1/report.csv", headers=token(client, "teacher")
    )
    disposition = response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="report-session-1-' in disposition
    assert disposition.endswith(".csv")
    # Кириллическое имя — только в filename* по RFC 5987.
    ascii_name = re.search(r'filename="([^"]+)"', disposition).group(1)
    assert ascii_name.isascii()
    assert "filename*=UTF-8''" in disposition


def test_pdf_является_настоящим_документом(client, filled):
    response = client.get(
        "/api/teacher/sessions/1/report.pdf", headers=token(client, "teacher")
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert response.content.rstrip().endswith(b"%%EOF")
    assert len(response.content) > 1000
    assert 'filename="report-session-1-' in response.headers["content-disposition"]


def test_pdf_содержит_кириллический_текст(client, filled):
    """Текст читается из документа, а не предполагается по факту сборки."""
    data = client.get(
        "/api/teacher/sessions/1/report.pdf", headers=token(client, "teacher")
    ).content
    text = pdf_text(data)

    assert "Отчёт о практическом занятии" in text
    assert "Иванов И.И." in text
    assert "Диспетчер ДДС" in text
    assert "Норматив взятия в работу" in text
    # Шрифт вшит в документ: на машине без PT Sans он откроется так же.
    assert b"/FontFile2" in data


def test_шрифт_отчёта_покрывает_всю_кириллицу():
    """Без глифа просмотрщик рисует пустой квадрат — проверяем весь алфавит."""
    from reportlab.pdfbase.ttfonts import TTFont

    face = TTFont(export.FONT_NAME, str(export.FONT_FILE)).face
    missing = [char for char in ALPHABET + "«»—№" if not face.charToGlyph.get(ord(char))]
    assert missing == []


def test_обучающемуся_выгрузка_закрыта(client, filled):
    headers = token(client, "student")
    assert client.get("/api/teacher/sessions/1/report.csv", headers=headers).status_code == 403
    assert client.get("/api/teacher/sessions/1/report.pdf", headers=headers).status_code == 403


def test_выгрузка_несуществующего_занятия(client):
    headers = token(client, "teacher")
    assert client.get("/api/teacher/sessions/99/report.csv", headers=headers).status_code == 404
    assert client.get("/api/teacher/sessions/99/report.pdf", headers=headers).status_code == 404
