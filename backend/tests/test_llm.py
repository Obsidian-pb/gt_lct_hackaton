import json

import pytest

from app.llm.openai_compatible import _is_local, _parse_json
from app.llm.stub import StubProvider


def test_разбор_json_в_markdown_блоке():
    """Модель оборачивает ответ в ```json вопреки response_format."""
    assert _parse_json('```json\n{"missing_points": []}\n```') == {"missing_points": []}


def test_разбор_json_без_обрамления():
    assert _parse_json('{"summary": "ок"}') == {"summary": "ок"}


def test_разбор_json_с_текстом_вокруг():
    assert _parse_json('Вот результат: {"a": 1} — готово')["a"] == 1


def test_невалидный_ответ_приводит_к_ошибке():
    with pytest.raises(json.JSONDecodeError):
        _parse_json("модель ничего не вернула")


@pytest.mark.parametrize(
    "url,local",
    [
        ("http://127.0.0.1:8095/v1", True),
        ("http://localhost:11434/v1", True),
        ("http://host.docker.internal:8095/v1", True),
        ("http://192.168.1.10:8000/v1", True),
        # Имя сервиса из сети compose: его знает только внутренний DNS Docker.
        ("http://llm:8080/v1", True),
        ("https://api.openai.com/v1", False),
    ],
)
def test_локальный_адрес_определяется(url, local):
    """К локальной модели ходим в обход HTTP_PROXY, к внешнему API — через него."""
    assert _is_local(url) is local


@pytest.mark.asyncio
async def test_заглушка_не_выставляет_нарушений():
    """Без модели проверка не выполняется — и это должно быть видно.

    Раньше заглушка сверяла по ключевым словам и штрафовала за верный ответ,
    изложенный своими словами. Ложное обвинение хуже отсутствия проверки.
    """
    review = await StubProvider().review_comment(
        comment="Кабель относится к Ростелекому, сведения направлены им по принадлежности",
        required_points=[
            "провод принадлежит «Ростелеком»",
            "информация передана по принадлежности",
        ],
        context="Обрыв провода",
    )
    assert review.missing_points == []
    assert review.available is False
