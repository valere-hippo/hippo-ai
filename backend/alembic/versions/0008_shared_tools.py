"""create shared tools table

Revision ID: 0008_shared_tools
Revises: 0007_model_registry_sync
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_shared_tools"
down_revision = "0007_model_registry_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_tools",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("tool_type", sa.String(length=40), nullable=False),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_ai_tools_name"),
        schema="hippoai",
    )
    op.create_index("ai_tools_name_idx", "ai_tools", ["name"], unique=False, schema="hippoai")


def downgrade() -> None:
    op.drop_index("ai_tools_name_idx", table_name="ai_tools", schema="hippoai")
    op.drop_table("ai_tools", schema="hippoai")
