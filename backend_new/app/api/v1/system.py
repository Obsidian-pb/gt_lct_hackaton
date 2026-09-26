from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import async_session_factory, get_session
from app.models.audit import AuditLog
from app.models.system import SystemSetting
from app.services.audit import AuditService

router = APIRouter(tags=["system"])
admin_only = require_roles("system_admin")


class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    value: dict
    description: str | None


class SettingUpsert(BaseModel):
    value: dict
    description: str | None = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID | None
    payload: dict
    created_at: object


@router.get("/system/health", summary="Панель мониторинга (окно 19 ТЗ)")
async def health(_: CurrentUser) -> dict:
    db_ok = True
    try:
        async with async_session_factory() as session:
            await session.execute(select(1))
    except Exception:
        db_ok = False
    return {"status": "ok", "database": "up" if db_ok else "down"}


@router.get("/system/settings", response_model=list[SettingOut], summary="Системные настройки")
async def list_settings(
    _: Annotated[object, Depends(admin_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SettingOut]:
    result = await session.execute(select(SystemSetting).order_by(SystemSetting.key))
    return [SettingOut.model_validate(s) for s in result.scalars().all()]


@router.put("/system/settings/{key}", response_model=SettingOut, summary="Обновление настройки")
async def upsert_setting(
    key: str,
    payload: SettingUpsert,
    current_user: CurrentUser,
    _: Annotated[object, Depends(admin_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SettingOut:
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = SystemSetting(key=key, value=payload.value, description=payload.description)
        session.add(setting)
    else:
        setting.value = payload.value
        if payload.description is not None:
            setting.description = payload.description
    setting.updated_by = current_user.id
    await session.commit()
    await session.refresh(setting)
    return SettingOut.model_validate(setting)


@router.get("/audit", response_model=list[AuditLogOut], summary="Журнал аудита (окно 26 ТЗ)")
async def list_audit(
    _: Annotated[object, Depends(admin_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLogOut]:
    items = await AuditService(session).list(limit=min(limit, 1000), offset=offset)
    return [AuditLogOut.model_validate(i) for i in items]