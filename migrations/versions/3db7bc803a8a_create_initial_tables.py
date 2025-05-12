"""Create initial tables

Revision ID: 3db7bc803a8a
Revises: 
Create Date: 2025-05-11 23:20:20.369656

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3db7bc803a8a'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
   """Upgrade schema."""
   # Create users table
   op.create_table(
       'users',
       sa.Column('id', sa.Integer(), primary_key=True, index=True),
       sa.Column('email', sa.String(), nullable=False, unique=True, index=True),
       sa.Column('hashed_password', sa.String(), nullable=True),
       sa.Column('full_name', sa.String()),
       sa.Column('is_active', sa.Boolean(), default=False),
       sa.Column('is_superuser', sa.Boolean(), default=False),
       sa.Column('email_verified', sa.Boolean(), default=False),
       sa.Column('verification_token', sa.String(), unique=True, nullable=True),
       sa.Column('verification_token_expires', sa.DateTime(timezone=True), nullable=True),
       sa.Column('google_id', sa.String(), unique=True, nullable=True),
       sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
       sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
   )
   
   # Create devices table
   op.create_table(
       'devices',
       sa.Column('id', sa.Integer(), primary_key=True, index=True),
       sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
       sa.Column('device_id', sa.String(), index=True),
       sa.Column('device_name', sa.String()),
       sa.Column('device_type', sa.String()),
       sa.Column('is_active', sa.Boolean(), default=True),
       sa.Column('last_active', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
       sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now())
   )
   
   # Create password_resets table
   op.create_table(
       'password_resets',
       sa.Column('id', sa.Integer(), primary_key=True),
       sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
       sa.Column('token', sa.String(), unique=True, index=True),
       sa.Column('expires_at', sa.DateTime()),
       sa.Column('used', sa.Boolean(), default=False)
   )
   
   # Create session_requests table
   op.create_table(
       'session_requests',
       sa.Column('id', sa.Integer(), primary_key=True, index=True),
       sa.Column('request_id', sa.String(), unique=True, index=True),
       sa.Column('from_user_id', sa.Integer(), sa.ForeignKey('users.id')),
       sa.Column('to_user_id', sa.Integer(), sa.ForeignKey('users.id')),
       sa.Column('status', sa.String(), default='pending'),
       sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
       sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now())
   )
   
   # Create active_sessions table
   op.create_table(
       'active_sessions',
       sa.Column('id', sa.Integer(), primary_key=True, index=True),
       sa.Column('session_id', sa.String(), unique=True, index=True),
       sa.Column('request_id', sa.String(), sa.ForeignKey('session_requests.request_id')),
       sa.Column('user1_id', sa.Integer(), sa.ForeignKey('users.id')),
       sa.Column('user2_id', sa.Integer(), sa.ForeignKey('users.id')),
       sa.Column('start_time', sa.DateTime(timezone=True), server_default=sa.func.now()),
       sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
       sa.Column('is_active', sa.Boolean(), default=True),
       sa.Column('metadata', sa.Text(), nullable=True)
   )

def downgrade() -> None:
   """Downgrade schema."""
   op.drop_table('active_sessions')
   op.drop_table('session_requests')
   op.drop_table('password_resets')
   op.drop_table('devices')
   op.drop_table('users')
