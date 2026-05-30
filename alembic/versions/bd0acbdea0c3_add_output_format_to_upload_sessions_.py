"""add output_format to upload_sessions and mvt to layer_type

Revision ID: bd0acbdea0c3
Revises: 784ef9cf78ca
Create Date: 2026-05-30 13:39:23.953611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'bd0acbdea0c3'
down_revision: Union[str, None] = '784ef9cf78ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('upload_sessions', sa.Column('output_format', sa.String(), nullable=False, server_default='raster'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('upload_sessions', 'output_format')
