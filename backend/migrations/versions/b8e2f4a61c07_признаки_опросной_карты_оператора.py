"""Признаки опросной карты, отмеченные оператором

Revision ID: b8e2f4a61c07
Revises: a4c1d9e27b30
Create Date: 2026-09-25 10:20:00.000000

В настоящем АРМ-112 «Пострадавшие», «Нет доступа», «Угроза людям» — кнопки
на карточке, и от них зависит список оповещения. До сих пор признаки задавал
только сценарий; теперь оператор отмечает их сам, а сценарий остаётся эталоном.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e2f4a61c07'
down_revision: Union[str, None] = 'a4c1d9e27b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'attempt',
        sa.Column('chosen_flags', sa.JSON(), server_default='[]', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('attempt', 'chosen_flags')
