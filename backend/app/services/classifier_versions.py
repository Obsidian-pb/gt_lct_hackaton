"""Редакции Единого классификатора происшествий, загружаемые администратором.

Классификатор правится не реже раза в год, а техническое задание требует
механизма импорта обновлений учебных материалов в ручном режиме. Здесь
живёт всё, что для этого нужно: загрузка xlsx новой редакции, переключение
действующей и выбор редакции для конкретного занятия.

Правило выбора редакции одно на весь комплекс:
  * у занятия есть своя редакция, зафиксированная при создании, — по ней
    строится опросная карта, считается эталон и оценивается работа, сколько
    бы редакций ни сменилось после;
  * пустая ссылка у занятия означает встроенную редакцию из файла поставки:
    так устроены все занятия, проведённые до появления загрузки;
  * там, где занятия нет (каталог для формирования сценариев, справочник),
    действует включённая редакция, а если не включена ни одна — встроенная.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.training import ClassifierVersion, TrainingSession
from app.models.user import User
from app.services.ekp import EKP, get_ekp
from app.services.ekp_import import ParseError, parse_workbook

__all__ = [
    "DuplicateVersion",
    "ParseError",
    "activate",
    "active_version",
    "current_ekp",
    "deactivate",
    "ekp_for_session",
    "ekp_for_version",
    "list_versions",
    "upload",
]


class DuplicateVersion(RuntimeError):
    """Такой файл или такое обозначение уже есть среди загруженных редакций."""


# Разобранные редакции по ключу (id, sha256). Контрольная сумма в ключе
# защищает от подмены: в тестах база пересоздаётся, и под тем же номером
# может оказаться другая редакция. Содержимое редакции после загрузки
# не меняется, поэтому устаревать записям кеша не с чего.
_cache: dict[tuple[int, str], EKP] = {}


def reset_cache() -> None:
    _cache.clear()


def list_versions(db: Session) -> list[ClassifierVersion]:
    """Загруженные редакции, новые сверху. Встроенная редакция строкой не хранится."""
    return list(
        db.scalars(select(ClassifierVersion).order_by(ClassifierVersion.id.desc())).all()
    )


def active_version(db: Session) -> ClassifierVersion | None:
    return db.scalar(select(ClassifierVersion).where(ClassifierVersion.is_active.is_(True)))


def upload(
    db: Session,
    *,
    data: bytes,
    label: str,
    source_name: str,
    note: str | None,
    actor: User,
) -> tuple[ClassifierVersion, list[str]]:
    """Разбирает xlsx и сохраняет редакцию. Загруженная редакция не включается.

    Включение — отдельное действие: администратор сначала видит число правил
    и предупреждения разбора, а уже потом решает, переводить ли на редакцию
    новые занятия.

    Возвращает редакцию и подписи подколонок, которых разбор не знает:
    новая редакция может завести признак, о котором комплекс ещё не слышал,
    и такой столбец не сработает ни при каких флагах опросной карты.
    Молчать об этом нельзя, но и отказывать из-за этого — тоже: иначе
    обновление классификатора ждало бы обновления самого комплекса.
    """
    digest = hashlib.sha256(data).hexdigest()
    same = db.scalar(select(ClassifierVersion).where(ClassifierVersion.sha256 == digest))
    if same is not None:
        raise DuplicateVersion(
            f"Этот файл уже загружен как редакция «{same.label}»: "
            "содержимое совпадает побайтно"
        )
    if db.scalar(select(ClassifierVersion).where(ClassifierVersion.label == label)):
        raise DuplicateVersion(f"Обозначение «{label}» уже занято другой редакцией")

    result = parse_workbook(data, source=source_name)
    version = ClassifierVersion(
        label=label,
        source_name=source_name[:512],
        sha256=digest,
        rule_count=result.rule_count,
        # Хранится разобранный вид, а не сам xlsx: во время занятия нужен
        # готовый классификатор, а не повторный разбор книги на каждый
        # запрос. Компактная запись без отступов — файл поставки с отступами
        # вдвое больше, а читает его здесь только код.
        content=json.dumps(
            result.payload, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8"),
        is_active=False,
        note=note,
        uploaded_by=actor,
    )
    db.add(version)
    db.flush()
    return version, result.unknown_variants


def activate(db: Session, version_id: int) -> ClassifierVersion:
    """Делает редакцию действующей. Включённой бывает не больше одной.

    Снятие признака со всех остальных идёт одним запросом, а не перебором:
    иначе между двумя сохранениями возможен миг с двумя включёнными.
    """
    version = db.get(ClassifierVersion, version_id)
    if version is None:
        raise LookupError("Редакция классификатора не найдена")
    db.execute(
        update(ClassifierVersion)
        .where(ClassifierVersion.id != version_id, ClassifierVersion.is_active.is_(True))
        .values(is_active=False)
    )
    version.is_active = True
    db.flush()
    return version


def deactivate(db: Session) -> ClassifierVersion | None:
    """Возвращает комплекс к встроенной редакции. Отдаёт ту, что была включена."""
    previous = active_version(db)
    if previous is not None:
        previous.is_active = False
        db.flush()
    return previous


def ekp_for_version(version: ClassifierVersion) -> EKP:
    key = (version.id, version.sha256)
    ekp = _cache.get(key)
    if ekp is None:
        # Только здесь читается отложенный столбец с содержимым.
        ekp = _cache[key] = EKP(version.content)
    return ekp


def ekp_for_session(session: TrainingSession) -> EKP:
    """Классификатор, по которому идёт и оценивается занятие."""
    if session.classifier_version_id is None:
        return get_ekp()
    return ekp_for_version(session.classifier_version)


def current_ekp(db: Session) -> EKP:
    """Классификатор для действий вне занятия: включённая редакция, иначе встроенная."""
    version = active_version(db)
    return get_ekp() if version is None else ekp_for_version(version)
