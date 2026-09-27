"""auth: пользователи, роли, права и системные роли

Revision ID: 0001_auth
Revises:
Create Date: 2026-09-26

"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_auth"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SYSTEM_ROLES = [
    {
        "id": UUID("00000000-0000-0000-0000-000000000101"),
        "code": "system_admin",
        "name": "Системный администратор",
        "description": "Настройки системы: ИИ, БД, мониторинг, резервное копирование, журналы, аудит",
    },
    {
        "id": UUID("00000000-0000-0000-0000-000000000102"),
        "code": "admin",
        "name": "Администратор",
        "description": "Пользователи, справочники, группы происшествий, контроль учебного процесса",
    },
    {
        "id": UUID("00000000-0000-0000-0000-000000000103"),
        "code": "teacher",
        "name": "Преподаватель",
        "description": "Учебные задачи, сценарии, тренировки, проверка карточек, отчёты",
    },
    {
        "id": UUID("00000000-0000-0000-0000-000000000104"),
        "code": "student",
        "name": "Обучающийся",
        "description": "Прохождение назначенных тренировок в эмуляторе АРМ-112",
    },
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    op.create_table(
        "users",
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
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("middle_name", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        schema="auth",
    )

    op.create_table(
        "roles",
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
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_roles_code")),
        schema="auth",
    )

    op.create_table(
        "permissions",
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
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("code", name=op.f("uq_permissions_code")),
        schema="auth",
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_user_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["auth.roles.id"],
            name=op.f("fk_user_roles_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
        schema="auth",
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["auth.roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["auth.permissions.id"],
            name=op.f("fk_role_permissions_permission_id_permissions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "role_id", "permission_id", name=op.f("pk_role_permissions")
        ),
        schema="auth",
    )

    # Системные роли: фиксированные UUID для переиспользования
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_system", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema="auth",
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        roles_table,
        [
            {
                "id": role["id"],
                "code": role["code"],
                "name": role["name"],
                "description": role["description"],
                "is_system": True,
                "created_at": now,
                "updated_at": now,
            }
            for role in _SYSTEM_ROLES
        ],
    )


def downgrade() -> None:
    op.drop_table("role_permissions", schema="auth")
    op.drop_table("user_roles", schema="auth")
    op.drop_table("permissions", schema="auth")
    op.drop_table("roles", schema="auth")
    op.drop_table("users", schema="auth")
    op.execute("DROP SCHEMA IF EXISTS auth")