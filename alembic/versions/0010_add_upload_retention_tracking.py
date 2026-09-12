"""add upload retention tracking

Revision ID: 0010
Revises: 0009_add_batch_group_tables
Create Date: 2026-09-10 01:21:29.804813

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, None] = '0009_add_batch_group_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('upload_sessions', sa.Column('pending_release', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('upload_sessions', sa.Column('released_at', sa.DateTime(timezone=True), nullable=True))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('upload_sessions', 'released_at')
    op.drop_column('upload_sessions', 'pending_release')