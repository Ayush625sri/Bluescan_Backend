"""Add session images table

Revision ID: 292764054bd0
Revises: 26fbca79896b
Create Date: 2025-05-24 05:55:15.561020

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '292764054bd0'
down_revision: Union[str, None] = '26fbca79896b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    # Create session_images table
    op.create_table('session_images',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('uploaded_by', sa.Integer(), nullable=True),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('thumbnail_path', sa.String(), nullable=True),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('analysis_status', sa.String(), nullable=True),
        sa.Column('analysis_results', sa.Text(), nullable=True),
        sa.Column('pollution_detected', sa.String(), nullable=True),
        sa.Column('severity_score', sa.Integer(), nullable=True),
        sa.Column('confidence_score', sa.Integer(), nullable=True),
        sa.Column('latitude', sa.String(), nullable=True),
        sa.Column('longitude', sa.String(), nullable=True),
        sa.Column('location_name', sa.String(), nullable=True),
        sa.Column('water_temperature', sa.String(), nullable=True),
        sa.Column('weather_conditions', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index(op.f('ix_session_images_id'), 'session_images', ['id'], unique=False)
    op.create_index(op.f('ix_session_images_session_id'), 'session_images', ['session_id'], unique=False)
    op.create_index(op.f('ix_session_images_uploaded_by'), 'session_images', ['uploaded_by'], unique=False)
    op.create_index(op.f('ix_session_images_created_at'), 'session_images', ['created_at'], unique=False)
    
    # Add default value for analysis_status
    op.execute("ALTER TABLE session_images ALTER COLUMN analysis_status SET DEFAULT 'pending'")


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_session_images_created_at'), table_name='session_images')
    op.drop_index(op.f('ix_session_images_uploaded_by'), table_name='session_images')
    op.drop_index(op.f('ix_session_images_session_id'), table_name='session_images')
    op.drop_index(op.f('ix_session_images_id'), table_name='session_images')
    
    # Drop table
    op.drop_table('session_images')