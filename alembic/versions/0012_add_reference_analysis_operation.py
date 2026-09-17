"""add operation to reference analysis jobs

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-14 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('reference_analysis_jobs', sa.Column('operation', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='intersect'))

def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('reference_analysis_jobs', 'operation')
