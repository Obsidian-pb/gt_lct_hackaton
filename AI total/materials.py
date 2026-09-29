"""Shared reading list for locally hosted or external methodical documents.

Этап 5: reads and writes are routed through Engine.materials_items/add, which
use the StorageAdapter (PostgreSQL + optional file mirror) when enabled.
"""
import uuid
from urllib.parse import urlsplit
from ai_core import now, require_text


def items(engine, owner=None):
    return engine.materials_items(owner=owner)


def add(engine, request):
    url = require_text(request.get('url'), 'Ссылка на материал', 2000)
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Нужна доступная ссылка http(s) на документ.')
    entry = {'id': 'material-' + uuid.uuid4().hex[:12],
             'title': require_text(request.get('title'), 'Название материала', 160),
             'url': url,
             'description': str(request.get('description') or '')[:1000],
             'teacher': require_text(request.get('teacher'), 'Преподаватель', 160),
             'created_at': now()}
    if request.get('_owner_id') is not None:
        entry['teacher_id'] = request['_owner_id']
    return engine.materials_add(entry)
