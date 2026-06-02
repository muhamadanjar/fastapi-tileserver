"""Initial schema with upload_sessions and layers tables

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create upload_sessions table
    op.create_table(
        'upload_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('layer_id', sa.String(), nullable=False),
        sa.Column('total_size', sa.Integer(), nullable=False),
        sa.Column('received_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('final_path', sa.String(), nullable=True),
        sa.Column('output_format', sa.String(), nullable=False, server_default='raster'),
        sa.Column('max_zoom', sa.Integer(), nullable=True),
        sa.Column('chunk_map', sa.JSON(), nullable=True, server_default='{}'),
        sa.Column('total_chunks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('uploaded_chunks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('chunk_size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create layers table
    op.create_table(
        'layers',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('upload_session_id', sa.String(), nullable=True),
        sa.Column('code', sa.String(), nullable=True),
        sa.Column('layer_type', sa.String(), nullable=False, server_default='tile'),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('file_type', sa.String(), nullable=False),
        sa.Column('tile_url_template', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('is_visible', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('opacity', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('sorting', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('file_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('bbox_west', sa.Float(), nullable=True),
        sa.Column('bbox_south', sa.Float(), nullable=True),
        sa.Column('bbox_east', sa.Float(), nullable=True),
        sa.Column('bbox_north', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['upload_session_id'], ['upload_sessions.id']),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('layers')
    op.drop_table('upload_sessions')
