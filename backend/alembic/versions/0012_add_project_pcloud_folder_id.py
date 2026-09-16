"""add pcloud folder id to projects

Revision ID: 0012_add_project_pcloud_folder_id
Revises: 0011_make_project_skills_library_nullable
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_add_project_pcloud_folder_id"
down_revision = "0011_make_project_skills_library_nullable"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.add_column("ai_projects", sa.Column("pcloud_folder_id", sa.Integer(), nullable=True), schema=TARGET_SCHEMA)


def downgrade() -> None:
    op.drop_column("ai_projects", "pcloud_folder_id", schema=TARGET_SCHEMA)
