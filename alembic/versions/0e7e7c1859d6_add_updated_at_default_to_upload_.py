"""add updated_at default to upload_sessions

Revision ID: 0e7e7c1859d6
Revises: b1e6a6bcc46d
Create Date: 2026-05-18 01:10:38.981418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e7e7c1859d6'
down_revision: Union[str, None] = 'b1e6a6bcc46d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('upload_sessions', 'updated_at',
               existing_type=sa.DateTime(),
               server_default=sa.func.current_timestamp())


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('upload_sessions', 'updated_at',
               existing_type=sa.DateTime(),
               server_default=None)
