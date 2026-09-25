"""Итоговый балл преподавателя

Revision ID: e5a1c8f3b927
Revises: d7b4e19c6a02
Create Date: 2026-09-25 17:30:00.000000

Преподаватель подтверждает итог работы числом; машинная оценка остаётся.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a1c8f3b927'
down_revision: Union[str, None] = 'd7b4e19c6a02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('evaluation', sa.Column('final_score', sa.Float(), nullable=True))
    op.add_column('evaluation', sa.Column('final_score_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('evaluation', sa.Column('final_score_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_evaluation_final_score_by', 'evaluation', 'app_user', ['final_score_by_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_evaluation_final_score_by', 'evaluation', type_='foreignkey')
    op.drop_column('evaluation', 'final_score_by_id')
    op.drop_column('evaluation', 'final_score_at')
    op.drop_column('evaluation', 'final_score')
