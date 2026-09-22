from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "import_classifier.py"
SPEC = importlib.util.spec_from_file_location("classifier_import", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
classifier_import = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = classifier_import
SPEC.loader.exec_module(classifier_import)


def test_official_classifier_is_filtered_and_parsed() -> None:
    parsed = classifier_import.parse_workbook(classifier_import.DEFAULT_WORKBOOK)

    assert len(parsed.rows) == 1137
    assert parsed.excluded_rows == 144
    assert len(parsed.group_names) == 24
    assert parsed.group_names[1] == "Пожары и задымления"
    assert parsed.group_names[2] == "ДТП"
    assert parsed.group_names[24] == "БПЛА"
    assert len({row.event_number for row in parsed.rows}) == 1137
    assert all(
        row.feature_1_label.casefold()
        != classifier_import.EXCLUSION_TEXT
        for row in parsed.rows
    )

    by_number = {row.event_number: row for row in parsed.rows}
    assert by_number[1010101].key == (1, 1, 1, 1)
    assert by_number[1010101].feature_1_label == "на улице"
    assert by_number[2010100].key == (2, 1, 1, 0)
    assert by_number[2010100].feature_3_label is None
    assert by_number[14030203].feature_3_code == 3
    assert by_number[14030203].feature_3_label is None
    assert by_number[14030205].feature_3_code == 5
    assert by_number[14030205].feature_3_label is None
