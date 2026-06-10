"""Add celery_task_id column to upload_sessions table

Revision ID: 0003_add_celery_task_id_to_upload_sessions
Revises: 0002_add_catalog_cols
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_add_celery_task_id'
down_revision: Union[str, None] = '0002_add_catalog_cols'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add celery_task_id column to store Celery task UUID for cancellation."""
    op.add_column('upload_sessions', sa.Column('celery_task_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove celery_task_id column."""
    op.drop_column('upload_sessions', 'celery_task_id')
