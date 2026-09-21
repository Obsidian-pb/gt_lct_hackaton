"""Add structured incident card details.

Revision ID: 0003_incident_card_details
Revises: 0002_classifier_structure
"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_incident_card_details"
down_revision: str | None = "0002_classifier_structure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "incident_card_details",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "exercise_revision_id",
            UUID,
            sa.ForeignKey("content.exercise_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("registered_by_name", sa.String(255), nullable=True),
        sa.Column("controlled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("controlled_by_name", sa.String(255), nullable=True),
        sa.Column("aon_phone", sa.String(32), nullable=True),
        sa.Column("applicant_phone", sa.String(32), nullable=True),
        sa.Column("scene_phone", sa.String(32), nullable=True),
        sa.Column("applicant_full_name", sa.String(255), nullable=True),
        sa.Column("applicant_status", sa.String(128), nullable=True),
        sa.Column("country", sa.String(128), nullable=True),
        sa.Column("federal_subject", sa.String(255), nullable=True),
        sa.Column("locality", sa.String(255), nullable=True),
        sa.Column("address_object", sa.String(255), nullable=True),
        sa.Column("administrative_district", sa.String(255), nullable=True),
        sa.Column("district", sa.String(255), nullable=True),
        sa.Column("street", sa.String(255), nullable=True),
        sa.Column("house", sa.String(32), nullable=True),
        sa.Column("building", sa.String(32), nullable=True),
        sa.Column("structure", sa.String(32), nullable=True),
        sa.Column("apartment", sa.String(32), nullable=True),
        sa.Column("entrance", sa.String(32), nullable=True),
        sa.Column("floor", sa.String(32), nullable=True),
        sa.Column("intercom_code", sa.String(64), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("descriptive_address", sa.Text(), nullable=True),
        sa.Column("incident_description", sa.Text(), nullable=True),
        sa.Column("vis_information", sa.Text(), nullable=True),
        sa.Column("control_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "exercise_revision_id",
            name="uq_incident_card_details_exercise_revision_id",
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="latitude_range",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="longitude_range",
        ),
        schema="content",
    )

    op.execute(
        """
        CREATE TRIGGER trg_incident_card_details_updated_at
        BEFORE UPDATE ON content.incident_card_details
        FOR EACH ROW EXECUTE FUNCTION audit.touch_updated_at()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_incident_card_details_updated_at "
        "ON content.incident_card_details"
    )
    op.drop_table("incident_card_details", schema="content")
