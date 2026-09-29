"""Storage mode configuration for the repository switch (Этап 5).

Priority: default 'files'  <  "storage.mode" in config.local.json  <  STORAGE_MODE env.

Modes:
- 'files'       — legacy JSON files only (default; existing tests/deployments).
- 'files-to-db' — dual-write: DB + file; reads prefer the DB and mirror files on
                  first access (transitional mode).
- 'db-only'     — PostgreSQL is the only source of truth; files are ignored.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MODE = 'files'
MODES = ('files', 'files-to-db', 'db-only')


def get_storage_config(config_path=None) -> dict:
    """Return {'mode': str} following the config priority above."""
    mode = DEFAULT_MODE
    path = Path(config_path) if config_path else (
        Path(__file__).resolve().parent / 'config.local.json')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        section = data.get('storage')
        if isinstance(section, dict) and section.get('mode') in MODES:
            mode = section['mode']
    except (OSError, ValueError):
        pass
    env = os.environ.get('STORAGE_MODE', '').strip().lower()
    if env in MODES:
        mode = env
    return {'mode': mode}