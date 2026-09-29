"""audit + system: журнал аудита и системные настройки

Revision ID: 0006_audit_system
Revises: 0005_training
Create Date: 2026-09-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_audit_system"
down_revision: Union[str, None] = "0005_training"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    op.execute("CREATE SCHEMA IF NOT EXISTS system")

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "retain_until",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP + INTERVAL '6 months'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["auth.users.id"],
            name=op.f("fk_audit_log_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.Index("ix_audit_log_created_at", "created_at"),
        sa.Index("ix_audit_log_actor_created", "actor_id", "created_at"),
        sa.Index("ix_audit_log_entity", "entity_type", "entity_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        schema="audit",
    )

    op.create_table(
        "system_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["auth.users.id"],
            name=op.f("fk_system_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_settings")),
        sa.UniqueConstraint("key", name=op.f("uq_system_settings_key")),
        schema="system",
    )


def downgrade() -> None:
    op.drop_table("system_settings", schema="system")
    op.drop_table("audit_log", schema="audit")
    op.execute("DROP SCHEMA IF EXISTS system")
    op.execute("DROP SCHEMA IF EXISTS audit")