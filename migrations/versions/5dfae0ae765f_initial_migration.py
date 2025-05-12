"""Initial migration

Revision ID: 5dfae0ae765f
Revises: 3db7bc803a8a
Create Date: 2025-05-12 07:04:42.584953

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dfae0ae765f'
down_revision: Union[str, None] = '3db7bc803a8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
