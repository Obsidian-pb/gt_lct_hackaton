"""Редакции классификатора и повтор проваленной карточки

Revision ID: a4c1d9e27b30
Revises: f7f77c2cb915
Create Date: 2026-09-23 12:10:00.000000

Одна миграция на две независимые доработки: они делались параллельно,
и две головы Alembic обошлись бы дороже, чем один общий шаг.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c1d9e27b30'
down_revision: Union[str, None] = 'f7f77c2cb915'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'classifier_version',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=64), nullable=False),
        sa.Column('source_name', sa.String(length=512), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('rule_count', sa.Integer(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('note', sa.String(length=500), nullable=True),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['app_user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('label'),
    )
    op.add_column(
        'training_session',
        sa.Column('repeat_failed', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column('training_session', sa.Column('classifier_version_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_training_session_classifier_version',
        'training_session', 'classifier_version', ['classifier_version_id'], ['id'],
    )
    op.add_column('attempt', sa.Column('repeat_of_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_attempt_repeat_of', 'attempt', 'attempt', ['repeat_of_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_attempt_repeat_of', 'attempt', type_='foreignkey')
    op.drop_column('attempt', 'repeat_of_id')
    op.drop_constraint('fk_training_session_classifier_version', 'training_session', type_='foreignkey')
    op.drop_column('training_session', 'classifier_version_id')
    op.drop_column('training_session', 'repeat_failed')
    op.drop_table('classifier_version')
