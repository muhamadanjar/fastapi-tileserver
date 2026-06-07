"""Add catalog metadata columns to layers table

Revision ID: 0002_add_catalog_columns_to_layers
Revises: 0001_initial_schema
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_add_catalog_cols'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add catalog metadata columns: abstract, topic_category, language."""
    op.add_column('layers', sa.Column('abstract', sa.Text(), nullable=True))
    op.add_column('layers', sa.Column('topic_category', sa.String(length=64), nullable=True))
    op.add_column('layers', sa.Column('language', sa.String(length=8), nullable=True, server_default='eng'))


def downgrade() -> None:
    """Remove catalog metadata columns."""
    op.drop_column('layers', 'language')
    op.drop_column('layers', 'topic_category')
    op.drop_column('layers', 'abstract')
