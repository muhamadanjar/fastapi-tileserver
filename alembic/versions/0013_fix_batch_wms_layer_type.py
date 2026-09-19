"""repair batch wms layers persisted as tile

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Align historical batch layers where output_format was wms/mvt but
    # layer_type was left as `tile` by the old _save_layer implementation.
    # This is a data repair only, no schema change.
    op.execute(sa.text("""
        UPDATE layers
        SET layer_type = 'wms', file_type = 'external'
        WHERE (file_metadata->>'output_format') = 'wms'
          AND layer_type != 'wms'
    """))
    op.execute(sa.text("""
        UPDATE layers
        SET layer_type = 'mvt', file_type = 'vector'
        WHERE (file_metadata->>'output_format') = 'mvt'
          AND layer_type != 'mvt'
    """))
    op.execute(sa.text("""
        UPDATE layers
        SET layer_type = 'tile', file_type = 'vector'
        WHERE (file_metadata->>'output_format') = 'raster'
          AND layer_type != 'tile'
    """))
    op.execute(sa.text("""
        UPDATE layers
        SET layer_type = 'postgis', file_type = 'vector'
        WHERE (file_metadata->>'output_format') = 'postgis'
          AND layer_type != 'postgis'
    """))


def downgrade() -> None:
    # No downgrade; repair is idempotent and preserves correct types.
    pass
