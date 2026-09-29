"""Storage adapter with the Engine.save/load/list_items interface (Этап 5).

The adapter hides whether the data lives in JSON files, PostgreSQL or both:
- 'files'       legacy file behaviour (no DB access at all);
- 'files-to-db' writes go to the DB and the file; reads prefer the DB and, on a
                miss, fall back to the file and mirror it into the DB;
- 'db-only'     PostgreSQL only.

Document formats are identical to what Engine/curriculum/materials already
write, so switching the backend does not change any API contract.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from storage_config import MODES, get_storage_config
from storage_repository import StorageRepository


class StorageUnavailable(RuntimeError):
    """The configured DB-backed mode cannot work without a reachable database."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, value) -> None:
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2),
                    encoding='utf-8')
    temp.replace(path)


class StorageAdapter:
    """Engine-compatible storage plus curriculum/material resource methods."""

    def __init__(self, directory=None, config=None, mode: Optional[str] = None):
        self.directory = Path(directory) if directory else (
            Path(__file__).resolve().parent / 'data')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.mode = (mode or get_storage_config(config).get('mode')
                     or 'files').strip().lower()
        if self.mode not in MODES:
            raise ValueError('Неизвестный режим хранилища: ' + self.mode)
        self._repo = StorageRepository(config) if self.mode != 'files' else None
        self._db_ready = None
        if self._repo is not None:
            self.ensure_schema()

    # ------------------------------------------------------------------ setup

    @property
    def db(self) -> bool:
        return self._repo is not None

    def ensure_schema(self) -> None:
        """Apply schema 2.4.0; propagate failures as StorageUnavailable."""
        try:
            self._repo.ensure_schema()
            self._db_ready = True
        except Exception as exc:  # noqa: BLE001 - surfaced to the launcher
            raise StorageUnavailable(
                'Не удалось подготовить хранилище PostgreSQL: ' + str(exc)) from exc

    # -------------------------------------------------------- file primitives

    def _file_path(self, identifier: str) -> Path:
        return self.directory / (identifier + '.json')

    def _file_save(self, item: dict) -> dict:
        _atomic_write(self._file_path(item['id']), item)
        return item

    def _file_load(self, identifier: str) -> dict:
        return json.loads(self._file_path(identifier).read_text(encoding='utf-8'))

    def _file_list(self, kind: str) -> List[dict]:
        result = []
        for path in sorted(self.directory.glob(kind + '-*.json'),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            result.append(json.loads(path.read_text(encoding='utf-8')))
        return result

    def _file_exists(self, identifier: str) -> bool:
        return self._file_path(identifier).exists()

    # ------------------------------------------------------- Engine interface

    def save(self, item: dict) -> dict:
        """Persist a task (t-*) or session (s-*) document."""
        item['updated_at'] = _now()
        if self.mode in ('files', 'files-to-db'):
            self._file_save(item)
        if self.db:
            kind = 't' if item['id'].startswith('t-') else 's'
            if kind == 't':
                self._repo.upsert_task(item)
            else:
                self._repo.upsert_session(item)
        return item

    def load(self, identifier: str) -> dict:
        """Return the full document; DB-first in DB-backed modes."""
        if self.db:
            try:
                return (self._repo.load_task(identifier)
                        if identifier.startswith('t-')
                        else self._repo.load_session(identifier))
            except FileNotFoundError:
                if self.mode == 'db-only':
                    raise
        doc = self._file_load(identifier)
        if self.db and self.mode == 'files-to-db':
            self.save(dict(doc))
        return doc

    def list_items(self, kind: str) -> List[dict]:
        """List documents of kind 't' or 's', newest first."""
        if self.db:
            items = (self._repo.list_tasks() if kind == 't'
                     else self._repo.list_sessions())
            if items or self.mode == 'db-only':
                return items
        docs = self._file_list(kind)
        if self.db and self.mode == 'files-to-db':
            for doc in docs:
                self.save(dict(doc))
        return docs

    def exists(self, identifier: str) -> bool:
        if self.db and identifier.startswith('t-'):
            return self._repo.exists_task(identifier)
        return self._file_exists(identifier)

    # ---------------------------------------------- curriculum/material access

    def _resource_file(self, identifier: str) -> Path:
        root = self.directory / 'curriculum'
        root.mkdir(parents=True, exist_ok=True)
        return root / (identifier + '.json')

    def _is_scenario(self, identifier: str) -> bool:
        return identifier.startswith('scenario-')

    def resource_save(self, item: dict) -> dict:
        item['updated_at'] = _now()
        if self.mode in ('files', 'files-to-db'):
            _atomic_write(self._resource_file(item['id']), item)
        if self.db:
            if self._is_scenario(item['id']):
                self._repo.upsert_scenario(item)
            else:
                self._repo.upsert_training(item)
        return item

    def resource_get(self, identifier: str) -> dict:
        if self.db:
            try:
                return (self._repo.load_scenario(identifier)
                        if self._is_scenario(identifier)
                        else self._repo.load_training(identifier))
            except FileNotFoundError:
                if self.mode == 'db-only':
                    raise
        doc = json.loads(self._resource_file(identifier).read_text(encoding='utf-8'))
        if doc.get('id') != identifier:
            raise ValueError('Учебный ресурс повреждён.')
        if self.db and self.mode == 'files-to-db':
            self.resource_save(dict(doc))
        return doc

    def resource_delete(self, identifier: str) -> dict:
        if self.mode in ('files', 'files-to-db'):
            path = self._resource_file(identifier)
            if path.exists():
                path.unlink()
        if self.db:
            if self._is_scenario(identifier):
                self._repo.delete_scenario(identifier)
            else:
                self._repo.delete_training(identifier)
        return {'deleted': True}

    def resource_list(self, kind: str) -> List[dict]:
        if self.db:
            items = (self._repo.list_scenarios() if kind == 'scenario'
                     else self._repo.list_trainings())
            if items or self.mode == 'db-only':
                return items
        root = self.directory / 'curriculum'
        if not root.exists():
            return []
        docs = []
        for path in sorted(root.glob(kind + '-*.json'),
                           key=lambda p: p.stat().st_mtime, reverse=True):
            docs.append(json.loads(path.read_text(encoding='utf-8')))
        if self.db and self.mode == 'files-to-db':
            for doc in docs:
                self.resource_save(dict(doc))
        return docs

    # ------------------------------------------------------------ materials

    def _materials_file(self) -> Path:
        root = self.directory / 'curriculum'
        root.mkdir(parents=True, exist_ok=True)
        return root / 'materials.json'

    def materials_items(self) -> List[dict]:
        if self.db:
            items = self._repo.list_materials()
            if items or self.mode == 'db-only':
                return items
        path = self._materials_file()
        rows = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        if self.db and self.mode == 'files-to-db':
            for row in rows:
                self._repo.upsert_material(dict(row))
        return rows

    def materials_add(self, entry: dict) -> dict:
        if self.mode in ('files', 'files-to-db'):
            path = self._materials_file()
            rows = (json.loads(path.read_text(encoding='utf-8'))
                    if path.exists() else [])
            rows.append(entry)
            _atomic_write(path, rows)
        if self.db:
            self._repo.upsert_material(entry)
        return entry