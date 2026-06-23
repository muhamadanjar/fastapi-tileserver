"""Add mbtiles columns to layers table

Revision ID: 0004_add_mbtiles
Revises: 0003_add_celery_task_id
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_add_mbtiles'
down_revision: Union[str, None] = '0003_add_celery_task_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add mbtiles columns to layers table for offline tile export."""
    op.add_column('layers', sa.Column('mbtiles_path', sa.String(), nullable=True))
    op.add_column('layers', sa.Column('mbtiles_status', sa.String(), nullable=True))
    op.add_column('layers', sa.Column('mbtiles_size_bytes', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Remove mbtiles columns from layers table."""
    op.drop_column('layers', 'mbtiles_size_bytes')
    op.drop_column('layers', 'mbtiles_status')
    op.drop_column('layers', 'mbtiles_path')
