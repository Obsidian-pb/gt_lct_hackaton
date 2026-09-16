"""Запись журнала аудита.

Журнал ведётся отдельно от бизнес-логики и никогда не мешает основному
действию: если запись не удалась, пользователь всё равно получает результат.
Терять действие из-за проблемы с журналом хуже, чем потерять строку журнала.
"""

from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import AuditAction, AuditEvent
from app.models.user import User

logger = logging.getLogger(__name__)


def client_ip(request: Request | None) -> str | None:
    """Адрес клиента с учётом обратного прокси перед приложением."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def record(
    db: Session,
    action: AuditAction,
    *,
    actor: User | None = None,
    actor_login: str | None = None,
    object_type: str | None = None,
    object_id: int | None = None,
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    try:
        db.add(
            AuditEvent(
                action=action,
                actor=actor,
                actor_login=actor_login or (actor.login if actor else "—"),
                object_type=object_type,
                object_id=object_id,
                detail=detail or {},
                ip_address=client_ip(request),
            )
        )
        db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось записать событие аудита %s: %s", action, exc)
