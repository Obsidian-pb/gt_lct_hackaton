"""Storage mode configuration for the repository switch (Этап 6).

Priority: default 'db-only' < "storage.mode" in config.local.json < STORAGE_MODE env.

Modes:
- 'files'       — deprecated legacy JSON files only.
- 'files-to-db' — deprecated dual-write migration mode.
- 'db-only'     — PostgreSQL is the source of truth (default).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_MODE = 'db-only'
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