"""create permissions and chat tables

Revision ID: 0002_permissions_chat
Revises: 0001_create_users
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_permissions_chat"
down_revision = "0001_create_users"
branch_labels = None
depend_on = None


def upgrade():
    # permission level enum
    permission_level = sa.Enum('READ', 'WRITE', 'ADMIN', name='permission_level')
    permission_level.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'ai_project_permissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('level', permission_level, nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        'ai_conversations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'ai_chat_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table('ai_chat_messages')
    op.drop_table('ai_conversations')
    op.drop_table('ai_project_permissions')
    sa.Enum(name='permission_level').drop(op.get_bind(), checkfirst=True)
