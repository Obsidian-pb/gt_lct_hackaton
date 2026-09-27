from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    payload: dict | None = None,
) -> None:
    """Записывает событие в журнал аудита (окно 26 ТЗ)."""
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    )


class AuditService:
    """Чтение журнала аудита."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, limit: int = 100, offset: int = 0) -> list[AuditLog]:
        result = await self._session.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())