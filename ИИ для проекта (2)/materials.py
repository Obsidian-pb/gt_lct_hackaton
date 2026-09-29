"""Shared reading list for locally hosted or external methodical documents."""
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from ai_core import now, require_text


def _path(engine):
    root = Path(engine.directory) / 'curriculum'
    root.mkdir(parents=True, exist_ok=True)
    return root / 'materials.json'


def items(engine):
    if getattr(engine, 'store', None) is not None:
        return engine.store.list_materials()
    path = _path(engine)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def add(engine, request):
    url = require_text(request.get('url'), 'Ссылка на материал', 2000)
    parsed = urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Нужна доступная ссылка http(s) на документ.')
    entry = {'id':'material-' + uuid.uuid4().hex[:12], 'title':require_text(request.get('title'), 'Название материала', 160),
             'url':url, 'description':str(request.get('description') or '')[:1000],
             'teacher':require_text(request.get('teacher'), 'Преподаватель', 160), 'created_at':now()}
    if getattr(engine, 'store', None) is not None:
        engine.store.add_material(entry)
        return entry
    rows = items(engine)
    rows.append(entry)
    temp = _path(engine).with_suffix('.tmp')
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(_path(engine))
    return entry
