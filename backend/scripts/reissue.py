"""Перевыдача учебных карточек: сбрасывает попытки и заново ставит отсчёт.

Нужна, чтобы показывать занятие несколько раз подряд, не пересоздавая базу:
после прогона карточки снова «только что направлены в службу», и норматив
в 30 секунд отсчитывается с нуля.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.training import Attempt, CardStatus  # noqa: E402


def reissue() -> None:
    with SessionLocal() as db:
        attempts = db.scalars(select(Attempt).order_by(Attempt.id)).all()
        if not attempts:
            print("Карточек нет — сначала запустите seed.py")
            return

        now = utcnow()
        for attempt in attempts:
            attempt.events.clear()
            attempt.evaluation = None
            attempt.issued_at = now
            attempt.opened_at = None
            attempt.finished_at = None
            attempt.card_status = CardStatus.REGISTERED
        db.commit()
        print(f"Перевыдано карточек: {len(attempts)}. Отсчёт норматива начат заново.")


if __name__ == "__main__":
    reissue()
