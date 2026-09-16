import pytest

from app.llm.stub import StubProvider


@pytest.mark.asyncio
async def test_заглушка_находит_нераскрытый_пункт():
    review = await StubProvider().review_comment(
        comment="Не обслуживаем эту территорию",
        required_points=[
            "не обслуживаем территорию",
            "информация передана в диспетчерскую Практика",
        ],
        context="Застревание в лифте",
    )
    assert review.missing_points == ["информация передана в диспетчерскую Практика"]


@pytest.mark.asyncio
async def test_заглушка_засчитывает_раскрытый_пункт():
    review = await StubProvider().review_comment(
        comment="Не обслуживаем территорию, информация передана в диспетчерскую Практика",
        required_points=["информация передана в диспетчерскую Практика"],
        context="Застревание в лифте",
    )
    assert review.missing_points == []
    assert review.available is True
