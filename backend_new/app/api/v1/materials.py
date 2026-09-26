from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.db.session import get_session
from app.models.content import StudyMaterial
from app.repositories.content import ContentRepository

router = APIRouter(prefix="/materials", tags=["materials"])
editor_access = require_roles("system_admin", "admin", "teacher")

STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage" / "materials"


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    file_path: str
    file_type: str | None
    file_size: int | None
    uploaded_by: UUID | None
    created_at: datetime


@router.get("", response_model=list[MaterialOut], summary="Справочная база (окно 18 ТЗ)")
async def list_materials(
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[MaterialOut]:
    items = await ContentRepository(session).list_materials()
    return [MaterialOut.model_validate(i) for i in items]


@router.post("", response_model=MaterialOut, status_code=201, summary="Загрузка материала")
async def upload_material(
    current_user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[object, Depends(editor_access)],
    title: str = Form(min_length=1, max_length=255),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> MaterialOut:
    ext = Path(file.filename or "").suffix.lower()
    filename = f"{uuid4().hex}{ext}"
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = STORAGE_DIR / filename
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    material = StudyMaterial(
        title=title,
        description=description,
        file_path=str(target),
        file_type=ext.lstrip(".") or None,
        file_size=target.stat().st_size,
        uploaded_by=current_user.id,
    )
    session.add(material)
    await session.commit()
    return MaterialOut.model_validate(material)


@router.get("/{material_id}/download", summary="Скачивание материала")
async def download_material(
    material_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    material = await ContentRepository(session).get_material(material_id)
    if material is None or material.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Материал не найден"
        )
    path = Path(material.file_path)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден на диске"
        )
    return FileResponse(path, filename=f"{material.title}{path.suffix}")


@router.delete("/{material_id}", status_code=204, summary="Удаление материала")
async def delete_material(
    material_id: UUID,
    _: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    editor: Annotated[object, Depends(editor_access)],
) -> None:
    material = await ContentRepository(session).get_material(material_id)
    if material is None or material.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Материал не найден"
        )
    now = datetime.now(timezone.utc)
    material.deleted_at = now
    material.purge_after = now + timedelta(days=180)
    await session.commit()