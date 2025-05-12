"""Updated users update_at field

Revision ID: 278b44d967dc
Revises: 5dfae0ae765f
Create Date: 2025-05-12 08:43:11.752571

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '278b44d967dc'
down_revision: Union[str, None] = '5dfae0ae765f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Update the updated_at column to have onupdate=func.now()
    op.alter_column('users', 'updated_at',
               existing_type=sa.DateTime(timezone=True),
               server_default=sa.text('now()'), 
               nullable=False)
    
    # Add a trigger to update the column
    op.execute("""
    CREATE OR REPLACE FUNCTION update_modified_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """)
    
    op.execute("""
    DROP TRIGGER IF EXISTS update_users_modtime ON users;
    CREATE TRIGGER update_users_modtime
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_modified_column();
    """)

def downgrade() -> None:
    # Remove trigger
    op.execute("DROP TRIGGER IF EXISTS update_users_modtime ON users;")
    op.execute("DROP FUNCTION IF EXISTS update_modified_column();")