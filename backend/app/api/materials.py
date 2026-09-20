"""Справочная база: инструкции и методические материалы.

Здесь сходятся два требования технического задания. Обучающийся обязан
иметь возможность просматривать инструкции и методические материалы,
преподаватель — создавать новые материалы и загружать дополнительные
ресурсы. Поэтому чтение открыто всем, кто вошёл в систему, а создание,
правка и публикация — только преподавателю, и только своего материала.

Неопубликованный материал виден одному автору. Незаконченная методичка
в руках обучающегося ничем не лучше неутверждённого сценария: и то и
другое учит неправильному, поэтому черновик из выдачи исключается.
"""

from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_teacher
from app.core.db import get_session
from app.models.training import TrainingMaterial
from app.models.user import User

router = APIRouter(prefix="/api/materials", tags=["Справочная база"])

# Предел размера вложения. Файл лежит в самой базе и целиком попадает
# в каждую её резервную копию, поэтому потолок нужен жёсткий. Десяти
# мегабайт хватает на методичку, инструкцию, презентацию или скан
# приказа — на всё, чем справочная база бывает на практике. Видеокурс
# в этот объём не уложится, и это намеренно: раздавать видео из таблицы
# базы данных нельзя, для него нужно отдельное хранилище.
MAX_FILE_BYTES = 10 * 1024 * 1024

# Перечень закрытый: принимается только то, чем бывает методический
# материал, — документ, таблица, презентация, простой текст, скан или
# схема. Исполняемые файлы и архивы не принимаются: учебный комплекс
# не файлообменник, а архив вдобавок скрывает содержимое от проверки
# преподавателем и от антивируса на сервере.
#
# Заявленный клиентом тип содержимого — не доказательство: его
# подставляет браузер по расширению, и подделать его тривиально. Поэтому
# рядом с каждым типом перечислены допустимые расширения, и они обязаны
# совпасть. Это не защита от подмены содержимого файла, но она отсекает
# попытку провести `.exe` под видом `application/pdf`.
ALLOWED_TYPES: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    "application/msword": (".doc",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (".pptx",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx",),
    "application/rtf": (".rtf",),
    "text/plain": (".txt",),
    "text/markdown": (".md",),
    "text/csv": (".csv",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
}

ALLOWED_EXTENSIONS = sorted({ext for exts in ALLOWED_TYPES.values() for ext in exts})


class MaterialIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = None


class MaterialPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    summary: str | None = Field(default=None, max_length=500)
    body: str | None = None


class MaterialOut(BaseModel):
    """Материал в списке: без текста, чтобы список не тащил всю базу целиком."""

    id: int
    title: str
    summary: str | None
    file_name: str | None
    media_type: str | None
    size_bytes: int | None
    published: bool
    author_id: int
    author_name: str
    created_at: datetime
    # Правку и публикацию интерфейс предлагает только автору — признак
    # считается на сервере, чтобы фронтенду не пришлось повторять правило.
    is_mine: bool


class MaterialDetailOut(MaterialOut):
    body: str | None


def _to_out(material: TrainingMaterial, user: User) -> MaterialOut:
    return MaterialOut(
        id=material.id,
        title=material.title,
        summary=material.summary,
        file_name=material.file_name,
        media_type=material.media_type,
        size_bytes=material.size_bytes,
        published=material.published,
        author_id=material.author_id,
        author_name=material.author.full_name,
        created_at=material.created_at,
        is_mine=material.author_id == user.id,
    )


def _to_detail(material: TrainingMaterial, user: User) -> MaterialDetailOut:
    return MaterialDetailOut(**_to_out(material, user).model_dump(), body=material.body)


def _visible(db: Session, material_id: int, user: User) -> TrainingMaterial:
    """Материал, который этому пользователю разрешено читать.

    Чужой черновик отдаётся как «не найден», а не как «нет прав»: иначе
    по коду ответа можно было бы пересчитать, сколько неопубликованных
    материалов готовит преподаватель.
    """
    material = db.get(TrainingMaterial, material_id)
    if material is None or not (material.published or material.author_id == user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Материал не найден")
    return material


def _own(db: Session, material_id: int, user: User) -> TrainingMaterial:
    """Материал, который этот преподаватель вправе изменять.

    Изменяет только автор. За содержание методички отвечает тот, чьё имя
    под ней стоит, поэтому правка чужого материала — даже опубликованного
    и даже другим преподавателем — запрещена.
    """
    material = db.get(TrainingMaterial, material_id)
    if material is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Материал не найден")
    if material.author_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Изменять материал может только его автор"
        )
    return material


@router.get("", response_model=list[MaterialOut])
def catalog(
    db: Session = Depends(get_session), user: User = Depends(get_current_user)
) -> list[MaterialOut]:
    """Справочная база: опубликованные материалы и собственные черновики."""
    materials = db.scalars(
        select(TrainingMaterial)
        .where(
            or_(
                TrainingMaterial.published.is_(True),
                TrainingMaterial.author_id == user.id,
            )
        )
        .order_by(TrainingMaterial.id.desc())
    ).all()
    return [_to_out(m, user) for m in materials]


@router.get("/{material_id}", response_model=MaterialDetailOut)
def read(
    material_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MaterialDetailOut:
    return _to_detail(_visible(db, material_id, user), user)


@router.post("", response_model=MaterialDetailOut, status_code=status.HTTP_201_CREATED)
def create(
    payload: MaterialIn,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> MaterialDetailOut:
    """Новый материал заводится черновиком: сначала его дописывают, потом публикуют."""
    material = TrainingMaterial(
        title=payload.title,
        summary=payload.summary,
        body=payload.body,
        published=False,
        author=user,
    )
    db.add(material)
    db.commit()
    return _to_detail(material, user)


@router.patch("/{material_id}", response_model=MaterialDetailOut)
def edit(
    material_id: int,
    payload: MaterialPatch,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> MaterialDetailOut:
    """Правка текста материала.

    Берутся только переданные поля: `exclude_unset` отличает «поле не
    трогали» от «поле очистили», иначе редактирование одного заголовка
    стирало бы текст материала.
    """
    material = _own(db, material_id, user)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(material, key, value)
    db.commit()
    return _to_detail(material, user)


@router.delete("/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    material_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> None:
    db.delete(_own(db, material_id, user))
    db.commit()


@router.post("/{material_id}/publish", response_model=MaterialDetailOut)
def publish(
    material_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> MaterialDetailOut:
    material = _own(db, material_id, user)
    # Пустая карточка в справочной базе хуже её отсутствия: обучающийся
    # тратит на неё время и не получает ничего.
    if not (material.body and material.body.strip()) and material.content is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Нечего публиковать: в материале нет ни текста, ни приложенного файла",
        )
    material.published = True
    db.commit()
    return _to_detail(material, user)


@router.post("/{material_id}/unpublish", response_model=MaterialDetailOut)
def unpublish(
    material_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> MaterialDetailOut:
    """Снятие с публикации — для устаревшей инструкции, которую ещё переписывают."""
    material = _own(db, material_id, user)
    material.published = False
    db.commit()
    return _to_detail(material, user)


@router.post("/{material_id}/file", response_model=MaterialDetailOut)
async def upload(
    material_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    user: User = Depends(require_teacher),
) -> MaterialDetailOut:
    """Загрузка приложенного файла. Повторная загрузка заменяет предыдущий."""
    material = _own(db, material_id, user)

    # Имя приходит от клиента и может содержать путь: берётся только
    # последний элемент, иначе в базу попадёт «../» из чужой файловой системы.
    name = PurePosixPath((file.filename or "").replace("\\", "/")).name
    extension = PurePosixPath(name).suffix.lower()
    media_type = (file.content_type or "").split(";")[0].strip().lower()
    if extension not in ALLOWED_TYPES.get(media_type, ()):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Такой файл в справочную базу не принимается. Допустимы: "
            + ", ".join(ALLOWED_EXTENSIONS),
        )

    # Заголовок Content-Length клиент вправе не прислать и может соврать,
    # поэтому предел проверяется по фактически прочитанным байтам:
    # читается на один байт больше разрешённого, и если он есть — отказ.
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ. "
            "Разделите материал или оставьте ссылку на внешний ресурс в тексте",
        )
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Файл пустой")

    material.file_name = name[:255]
    material.media_type = media_type
    material.content = content
    material.size_bytes = len(content)
    db.commit()
    return _to_detail(material, user)


def _content_disposition(material: TrainingMaterial) -> str:
    """Заголовок вложения с русским именем файла и латинским запасным.

    Кириллица в filename= ломается в части браузеров, поэтому основное имя
    латиницей, а читаемое исходное передаётся в filename* по RFC 5987.
    """
    name = material.file_name or f"material-{material.id}"
    extension = PurePosixPath(name).suffix.lower()
    return (
        f'attachment; filename="material-{material.id}{extension}"; '
        f"filename*=UTF-8''{quote(name)}"
    )


@router.get("/{material_id}/file", response_class=Response)
def download(
    material_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """Скачивание приложенного файла — доступно всем, кому виден материал."""
    material = _visible(db, material_id, user)
    if material.content is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "К материалу не приложен файл"
        )
    return Response(
        content=material.content,
        media_type=material.media_type or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(material)},
    )
