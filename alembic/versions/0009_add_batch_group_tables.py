"""add batch, dataset, layer_group, layer_group_members, code_reservations tables

Revision ID: 0009_add_batch_group_tables
Revises: 0008_add_analysis_results_table
Create Date: 2026-01-15 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_add_batch_group_tables"
down_revision = "0008_add_analysis_results_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batches
    op.create_table(
        "batches",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("upload_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="inspecting"),
        sa.Column("source_digest", sa.String(), nullable=False, server_default=""),
        sa.Column("mode", sa.String(), nullable=False, server_default="separate"),
        sa.Column("output_format", sa.String(), nullable=False, server_default="raster"),
        sa.Column("max_zoom", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("group_id", sa.String(), nullable=True),
        sa.Column("task_token", sa.String(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batches_upload_id"), "batches", ["upload_id"], unique=False)
    op.create_index(op.f("ix_batches_group_id"), "batches", ["group_id"], unique=False)
    op.create_foreign_key(
        "fk_batches_upload_id_upload_sessions",
        "batches",
        "upload_sessions",
        ["upload_id"],
        ["id"],
    )

    # datasets
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("geometry", sa.String(), nullable=False, server_default=""),
        sa.Column("feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("style", sa.JSON(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("layer_id", sa.String(), nullable=True),
        sa.Column("code", sa.String(), nullable=False, server_default=""),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(), nullable=False, server_default="detected"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_datasets_batch_id"), "datasets", ["batch_id"], unique=False)
    op.create_foreign_key(
        "fk_datasets_batch_id_batches",
        "datasets",
        "batches",
        ["batch_id"],
        ["id"],
    )
    # layer_id on datasets is a deterministic pre-publish identifier; the
    # actual layers row is created only after processing, so no FK to layers.
    # Referential integrity is enforced at the application layer via the
    # layer-deletion guard (deletion_guard in MapBatches).

    # layer_groups
    op.create_table(
        "layer_groups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("output_format", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_layer_groups_code"), "layer_groups", ["code"], unique=True)

    # layer_group_members
    op.create_table(
        "layer_group_members",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("layer_id", sa.String(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sorting", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_layer_group_members_group_id"), "layer_group_members", ["group_id"], unique=False)
    op.create_index(op.f("ix_layer_group_members_layer_id"), "layer_group_members", ["layer_id"], unique=False)
    op.create_foreign_key(
        "fk_layer_group_members_group_id_layer_groups",
        "layer_group_members",
        "layer_groups",
        ["group_id"],
        ["id"],
    )
    # Same rationale as datasets.layer_id: member layers are registered by
    # deterministic id before the layer row exists.

    # code_reservations
    op.create_table(
        "code_reservations",
        sa.Column("id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_code_reservations_code"), "code_reservations", ["code"], unique=True)


def downgrade() -> None:
    op.drop_table("code_reservations")
    op.drop_table("layer_group_members")
    op.drop_table("layer_groups")
    op.drop_table("datasets")
    op.drop_table("batches")
