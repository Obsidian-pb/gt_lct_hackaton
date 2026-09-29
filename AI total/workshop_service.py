"""Business logic for the master-workshop REST layer (Этап 5, Фаза 4).

Cards live in PostgreSQL (workshop_card + reference/version/event/dialogue);
the browser document format of workshop-store.js v1 is preserved as-is in
workshop_card.content, so the frontend round-trips without format changes.
Imported cards are upserted by their unique number (project decision №7).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from storage_repository import StorageRepository


class WorkshopError(RuntimeError):
    """Workshop-level failure with an HTTP-like status."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def _repo() -> StorageRepository:
    return StorageRepository()


def _require_text(value, label, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise WorkshopError(422, 'invalid_field',
                            f'{label}: нужен непустой текст до {limit} символов.')
    return value.strip()


def _content_required(content) -> dict:
    if not isinstance(content, dict) or not isinstance(content.get('fields'), dict):
        raise WorkshopError(422, 'invalid_content',
                            'Карточка должна содержать объект content.fields.')
    return content


def list_cards() -> List[dict]:
    return _repo().workshop_list()


def get_card(reference: str) -> dict:
    try:
        return _repo().workshop_get(_require_text(reference, 'Номер карточки', 64))
    except FileNotFoundError as exc:
        raise WorkshopError(404, 'not_found', 'Карточка мастерской не найдена.') from None


def create_card(content, author_id) -> dict:
    content = _content_required(content)
    return _repo().workshop_create(content, _author(author_id))


def update_card(reference: str, content, author_id) -> dict:
    content = _content_required(content)
    try:
        return _repo().workshop_update(_require_text(reference, 'Номер карточки', 64),
                                       content, _author(author_id))
    except FileNotFoundError:
        raise WorkshopError(404, 'not_found', 'Карточка мастерской не найдена.') from None


def approve_card(reference: str, review, author_id) -> dict:
    review = review if isinstance(review, dict) else {}
    teacher = _require_text(review.get('teacher'), 'Преподаватель', 160)
    review = {'teacher': teacher,
              'note': str(review.get('note') or '')[:2000],
              'at': review.get('at')}
    try:
        return _repo().workshop_approve(_require_text(reference, 'Номер карточки', 64),
                                        review, _author(author_id))
    except FileNotFoundError:
        raise WorkshopError(404, 'not_found', 'Карточка мастерской не найдена.') from None


def reopen_card(reference: str, author_id) -> dict:
    try:
        return _repo().workshop_reopen(_require_text(reference, 'Номер карточки', 64),
                                       _author(author_id))
    except FileNotFoundError:
        raise WorkshopError(404, 'not_found', 'Карточка мастерской не найдена.') from None


def delete_card(reference: str) -> dict:
    deleted = _repo().workshop_delete(_require_text(reference, 'Номер карточки', 64))
    if not deleted:
        raise WorkshopError(404, 'not_found', 'Карточка мастерской не найдена.')
    return {'deleted': True}


def import_cards(cards, author_id) -> dict:
    if not isinstance(cards, list) or not 1 <= len(cards) <= 1000:
        raise WorkshopError(422, 'invalid_cards',
                            'Импортируйте от 1 до 1000 карточек.')
    imported = 0
    errors: List[str] = []
    for index, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            errors.append(f'#{index}: не объект')
            continue
        try:
            _repo().workshop_create(card, _author(author_id))
            imported += 1
        except Exception as exc:  # noqa: BLE001 - report per-card import errors
            errors.append(f'#{index}: {str(exc)[:200]}')
    return {'imported': imported, 'errors': errors}


def _author(author_id) -> Optional[int]:
    """Explicit author_id or the authenticated user id from the JWT payload."""
    if author_id is None:
        return None
    try:
        return int(author_id)
    except (TypeError, ValueError):
        return None