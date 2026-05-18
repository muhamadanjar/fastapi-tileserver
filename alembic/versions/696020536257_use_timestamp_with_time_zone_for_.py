"""use TIMESTAMP WITH TIME ZONE for datetime fields

Revision ID: 696020536257
Revises: 0e7e7c1859d6
Create Date: 2026-05-18 01:22:08.218576

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '696020536257'
down_revision: Union[str, None] = '0e7e7c1859d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change TIMESTAMP WITHOUT TIME ZONE to TIMESTAMP WITH TIME ZONE."""
    op.alter_column('upload_sessions', 'created_at',
                   existing_type=sa.DateTime(timezone=False),
                   type_=sa.DateTime(timezone=True))
    op.alter_column('upload_sessions', 'updated_at',
                   existing_type=sa.DateTime(timezone=False),
                   type_=sa.DateTime(timezone=True))
    op.alter_column('layers', 'created_at',
                   existing_type=sa.DateTime(timezone=False),
                   type_=sa.DateTime(timezone=True))
    op.alter_column('layers', 'updated_at',
                   existing_type=sa.DateTime(timezone=False),
                   type_=sa.DateTime(timezone=True))


def downgrade() -> None:
    """Revert to TIMESTAMP WITHOUT TIME ZONE."""
    op.alter_column('upload_sessions', 'created_at',
                   existing_type=sa.DateTime(timezone=True),
                   type_=sa.DateTime(timezone=False))
    op.alter_column('upload_sessions', 'updated_at',
                   existing_type=sa.DateTime(timezone=True),
                   type_=sa.DateTime(timezone=False))
    op.alter_column('layers', 'created_at',
                   existing_type=sa.DateTime(timezone=True),
                   type_=sa.DateTime(timezone=False))
    op.alter_column('layers', 'updated_at',
                   existing_type=sa.DateTime(timezone=True),
                   type_=sa.DateTime(timezone=False))
