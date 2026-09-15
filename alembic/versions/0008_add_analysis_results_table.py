"""add analysis_results table

Revision ID: 0008_add_analysis_results_table
Revises: 0007
Create Date: 2026-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_add_analysis_results_table"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("layer_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("input_layer_a_id", sa.String(), nullable=False),
        sa.Column("input_layer_b_id", sa.String(), nullable=True),
        sa.Column("output_name", sa.String(), nullable=True),
        sa.Column("feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_null_geometry", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("result_file_path", sa.String(), nullable=True),
        sa.Column("ephemeral", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(), nullable=False, server_default="done"),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("bbox_west", sa.Float(), nullable=True),
        sa.Column("bbox_south", sa.Float(), nullable=True),
        sa.Column("bbox_east", sa.Float(), nullable=True),
        sa.Column("bbox_north", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_results_layer_id"), "analysis_results", ["layer_id"], unique=False)
    op.create_foreign_key(
        "fk_analysis_results_layer_id_layers",
        "analysis_results",
        "layers",
        ["layer_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_table("analysis_results")
