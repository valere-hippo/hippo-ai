"""add pcloud path to projects

Revision ID: 0010_add_project_pcloud_path
Revises: 0009_expand_tools_execution_fields
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_add_project_pcloud_path"
down_revision = "0009_expand_tools_execution_fields"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.add_column("ai_projects", sa.Column("pcloud_path", sa.String(length=1000), nullable=True), schema=TARGET_SCHEMA)


def downgrade() -> None:
    op.drop_column("ai_projects", "pcloud_path", schema=TARGET_SCHEMA)
