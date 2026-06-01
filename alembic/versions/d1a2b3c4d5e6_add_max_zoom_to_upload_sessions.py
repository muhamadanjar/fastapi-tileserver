"""add max_zoom to upload_sessions for user-defined tile zoom control

Revision ID: d1a2b3c4d5e6
Revises: c3f7d5e2a1b4
Create Date: 2026-06-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a2b3c4d5e6'
down_revision: Union[str, None] = 'c3f7d5e2a1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('upload_sessions', sa.Column('max_zoom', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('upload_sessions', 'max_zoom')
