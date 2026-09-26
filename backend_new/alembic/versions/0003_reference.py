"""reference: статусы сценариев, статусы заявителей, роли обучающихся

Revision ID: 0003_reference
Revises: 0002_catalog
Create Date: 2026-09-26

"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_reference"
down_revision: Union[str, None] = "0002_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_SCENARIO_STATUSES = [
    ("00000000-0000-0000-0000-000000000201", "draft", "Черновик", 10),
    ("00000000-0000-0000-0000-000000000202", "approved", "Утверждён", 20),
    ("00000000-0000-0000-0000-000000000203", "archived", "Архивный", 30),
]

_SEED_APPLICANT_STATUSES = [
    ("00000000-0000-0000-0000-000000000301", "participant", "Участник", 10),
    ("00000000-0000-0000-0000-000000000302", "eyewitness", "Очевидец", 20),
    ("00000000-0000-0000-0000-000000000303", "relative", "Родственник", 30),
]

_SEED_TRAINING_ROLES = [
    (
        "00000000-0000-0000-0000-000000000401",
        "operator_112",
        "Оператор-112",
        "Принимает вызов и заполняет карточку происшествия",
    ),
    (
        "00000000-0000-0000-0000-000000000402",
        "dispatcher_dds",
        "Диспетчер ДДС",
        "Проверяет карточку и направляет её в службы",
    ),
    (
        "00000000-0000-0000-0000-000000000403",
        "service_dispatcher",
        "Диспетчер службы",
        "Отрабатывает карточку в рамках своей службы",
    ),
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS reference")

    op.create_table(
        "scenario_statuses",
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_statuses")),
        sa.UniqueConstraint("code", name=op.f("uq_scenario_statuses_code")),
        schema="reference",
    )

    op.create_table(
        "applicant_statuses",
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
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applicant_statuses")),
        sa.UniqueConstraint("code", name=op.f("uq_applicant_statuses_code")),
        schema="reference",
    )

    op.create_table(
        "training_roles",
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
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.CheckConstraint(
            "code IN ('operator_112', 'dispatcher_dds', 'service_dispatcher')",
            name=op.f("ck_training_roles_code_values"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_roles")),
        sa.UniqueConstraint("code", name=op.f("uq_training_roles_code")),
        schema="reference",
    )

    # Сид справочников
    now = datetime.now(timezone.utc)

    scenario_statuses = sa.table(
        "scenario_statuses",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema="reference",
    )
    op.bulk_insert(
        scenario_statuses,
        [
            {
                "id": UUID(item[0]),
                "code": item[1],
                "name": item[2],
                "sort_order": item[3],
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for item in _SEED_SCENARIO_STATUSES
        ],
    )

    applicant_statuses = sa.table(
        "applicant_statuses",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema="reference",
    )
    op.bulk_insert(
        applicant_statuses,
        [
            {
                "id": UUID(item[0]),
                "code": item[1],
                "name": item[2],
                "sort_order": item[3],
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for item in _SEED_APPLICANT_STATUSES
        ],
    )

    training_roles = sa.table(
        "training_roles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema="reference",
    )
    op.bulk_insert(
        training_roles,
        [
            {
                "id": UUID(item[0]),
                "code": item[1],
                "name": item[2],
                "description": item[3],
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for item in _SEED_TRAINING_ROLES
        ],
    )


def downgrade() -> None:
    op.drop_table("training_roles", schema="reference")
    op.drop_table("applicant_statuses", schema="reference")
    op.drop_table("scenario_statuses", schema="reference")
    op.execute("DROP SCHEMA IF EXISTS reference")