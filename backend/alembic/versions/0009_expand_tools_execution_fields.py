"""expand tool execution fields

Revision ID: 0009_expand_tools_execution_fields
Revises: 0008_shared_tools
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_expand_tools_execution_fields"
down_revision = "0008_shared_tools"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.add_column("ai_tools", sa.Column("arguments", sa.Text(), nullable=True), schema=TARGET_SCHEMA)
    op.add_column("ai_tools", sa.Column("working_directory", sa.Text(), nullable=True), schema=TARGET_SCHEMA)
    op.add_column("ai_tools", sa.Column("platform", sa.String(length=20), nullable=True), schema=TARGET_SCHEMA)
    op.add_column("ai_tools", sa.Column("timeout_seconds", sa.Integer(), nullable=True), schema=TARGET_SCHEMA)
    op.add_column(
        "ai_tools",
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=TARGET_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("ai_tools", "requires_confirmation", schema=TARGET_SCHEMA)
    op.drop_column("ai_tools", "timeout_seconds", schema=TARGET_SCHEMA)
    op.drop_column("ai_tools", "platform", schema=TARGET_SCHEMA)
    op.drop_column("ai_tools", "working_directory", schema=TARGET_SCHEMA)
    op.drop_column("ai_tools", "arguments", schema=TARGET_SCHEMA)
