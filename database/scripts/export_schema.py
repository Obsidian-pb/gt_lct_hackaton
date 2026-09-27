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
        config.set_main_option("script_location", str(ROOT / "alembic"))
        command.upgrade(config, "head", sql=True)
    # Keep earlier generated migrations byte-for-byte stable while cleaning new SQL.
    contents = OUTPUT.read_text(encoding="utf-8")
    marker = "-- Running upgrade 0005_classifier_import_fields -> 0006_card_services"
    old_sql, separator, new_sql = contents.partition(marker)
    if not separator:
        raise RuntimeError("The current migration was not included in the SQL export")
    OUTPUT.write_text(
        old_sql + separator + "\n".join(line.rstrip() for line in new_sql.split("\n")),
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
