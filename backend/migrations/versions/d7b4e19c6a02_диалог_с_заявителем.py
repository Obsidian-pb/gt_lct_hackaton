"""Диалог оператора с заявителем

Revision ID: d7b4e19c6a02
Revises: c3f9a2d7e514
Create Date: 2026-09-25 15:10:00.000000

Вопросы оператора заявителю и ответы модели хранятся при попытке.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b4e19c6a02'
down_revision: Union[str, None] = 'c3f9a2d7e514'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'attempt',
        sa.Column('dialogue', sa.JSON(), server_default='[]', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('attempt', 'dialogue')
