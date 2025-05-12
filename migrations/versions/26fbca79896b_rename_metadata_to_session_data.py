"""rename metadata to session_data

Revision ID: 26fbca79896b
Revises: 278b44d967dc
Create Date: 2025-05-13 03:46:28.324192

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26fbca79896b'
down_revision: Union[str, None] = '278b44d967dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade():
    # For PostgreSQL - if you're using a different database, adapt as needed
    op.alter_column('active_sessions', 'metadata', new_column_name='session_data')


def downgrade():
    # Downgrade operation
    op.alter_column('active_sessions', 'session_data', new_column_name='metadata')
