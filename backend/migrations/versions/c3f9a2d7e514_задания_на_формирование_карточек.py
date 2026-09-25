"""Задания на формирование карточек в фоне

Revision ID: c3f9a2d7e514
Revises: b8e2f4a61c07
Create Date: 2026-09-25 10:40:00.000000

Формирование карточек моделью переведено в фон: задание хранится в базе,
чтобы ход работы был виден после перезапуска сервера.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f9a2d7e514'
down_revision: Union[str, None] = 'b8e2f4a61c07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generation_job',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('group', sa.String(length=255), nullable=False),
        sa.Column('difficulty', sa.Integer(), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('requested', sa.Integer(), nullable=False),
        sa.Column('finished', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created', sa.Integer(), server_default='0', nullable=False),
        sa.Column('state', sa.Enum('RUNNING', 'DONE', 'FAILED', name='generationstate', native_enum=False, length=16), server_default='RUNNING', nullable=False),
        sa.Column('scenario_ids', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['service_id'], ['dispatch_service.id']),
        sa.ForeignKeyConstraint(['teacher_id'], ['app_user.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('generation_job')
