"""add upload artifact reference

Revision ID: 0006_add_upload_artifact_ref
Revises: 0005_add_survey_schema
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_add_upload_artifact_ref"
down_revision = "0005_add_survey_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("upload_sessions", sa.Column("artifact_id", sa.String(), nullable=True))
    op.add_column("upload_sessions", sa.Column("artifact_lease_id", sa.String(), nullable=True))
    op.add_column("upload_sessions", sa.Column("artifact_handoff_id", sa.String(), nullable=True))
    op.create_index("ix_upload_sessions_artifact_id", "upload_sessions", ["artifact_id"], unique=False)
    op.create_index(
        "ix_upload_sessions_artifact_handoff_id",
        "upload_sessions",
        ["artifact_handoff_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_upload_sessions_artifact_id", table_name="upload_sessions")
    op.drop_index("ix_upload_sessions_artifact_handoff_id", table_name="upload_sessions")
    op.drop_column("upload_sessions", "artifact_handoff_id")
    op.drop_column("upload_sessions", "artifact_lease_id")
    op.drop_column("upload_sessions", "artifact_id")
