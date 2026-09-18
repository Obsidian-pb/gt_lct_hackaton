from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "schema.sql"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
        config = Config(str(ROOT / "alembic.ini"), output_buffer=stream)
        command.upgrade(config, "head", sql=True)


if __name__ == "__main__":
    main()
