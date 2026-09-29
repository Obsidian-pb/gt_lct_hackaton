"""PostgreSQL connection settings for the data layer.

Defaults match the project connection string. Values can be overridden by
environment variables (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD) or by
a "postgres" section inside config.local.json (not committed to the repo).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent

DEFAULT_DB_CONFIG: Dict[str, object] = {
    'host': 'postgres81.1gb.ru',
    'port': 5432,
    'dbname': 'xgb_lct_hack',
    'user': 'xgb_lct_hack',
    'password': 'HBy-y9AxR8DU',
    'connect_timeout': 10,
    'sslmode': 'prefer',  # prefer | require | disable
}

_ENV_KEYS = {
    'PGHOST': 'host',
    'PGPORT': 'port',
    'PGDATABASE': 'dbname',
    'PGUSER': 'user',
    'PGPASSWORD': 'password',
    'PGSSLMODE': 'sslmode',
}


def _load_local_section() -> Dict[str, object]:
    """Read the optional "postgres" section from config.local.json."""
    path = ROOT / 'config.local.json'
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    section = data.get('postgres') if isinstance(data, dict) else None
    return dict(section) if isinstance(section, dict) else {}


def get_db_config() -> Dict[str, object]:
    """Return effective connection settings: defaults < config.local.json < env."""
    config = dict(DEFAULT_DB_CONFIG)
    config.update(_load_local_section())
    for env_name, field in _ENV_KEYS.items():
        value = os.environ.get(env_name)
        if value:
            config[field] = int(value) if field == 'port' else value
    return config
