from alembic import op
import sqlalchemy as sa

revision = '0005_add_survey_schema'
down_revision = '0004_add_mbtiles'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('geometry_type', sa.String(), nullable=False),
        sa.Column('form_schema', sa.JSON(), nullable=False),
        sa.Column('layer_id', sa.String(), sa.ForeignKey('layers.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'features',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False, index=True),
        sa.Column('geometry', sa.JSON(), nullable=False),
        sa.Column('attributes', sa.JSON(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        'attachments',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id'), nullable=False, index=True),
        sa.Column('feature_id', sa.String(), nullable=True, index=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('stored_path', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('attachments')
    op.drop_table('features')
    op.drop_table('projects')
