"""add chunk_map fields to upload_sessions for resume capability

Revision ID: c3f7d5e2a1b4
Revises: bd0acbdea0c3
Create Date: 2026-05-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f7d5e2a1b4'
down_revision: Union[str, None] = 'bd0acbdea0c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('upload_sessions', sa.Column('chunk_map', sa.JSON(), nullable=True, server_default='{}'))
    op.add_column('upload_sessions', sa.Column('total_chunks', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('upload_sessions', sa.Column('uploaded_chunks', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('upload_sessions', sa.Column('chunk_size', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('upload_sessions', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('upload_sessions', 'expires_at')
    op.drop_column('upload_sessions', 'chunk_size')
    op.drop_column('upload_sessions', 'uploaded_chunks')
    op.drop_column('upload_sessions', 'total_chunks')
    op.drop_column('upload_sessions', 'chunk_map')
