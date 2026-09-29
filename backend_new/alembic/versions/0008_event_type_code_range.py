"""Расширение диапазона кода Группы происшествий (код «Г»)

Классификатор «клссы событий.xlsx» содержит 22+ групп, а исходное
ограничение допускало только 1..9.

Revision ID: 0008_event_type_code_range
Revises: 0007_classify_task_card_fields
Create Date: 2026-09-27
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_event_type_code_range"
down_revision: Union[str, None] = "0007_classify_task_card_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_event_types_code_range"),
        "event_types",
        type_="check",
        schema="catalog",
    )
    op.create_check_constraint(
        op.f("ck_event_types_code_range"),
        "event_types",
        "code BETWEEN 1 AND 99",
        schema="catalog",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_event_types_code_range"),
        "event_types",
        type_="check",
        schema="catalog",
    )
    op.create_check_constraint(
        op.f("ck_event_types_code_range"),
        "event_types",
        "code BETWEEN 1 AND 9",
        schema="catalog",
    )