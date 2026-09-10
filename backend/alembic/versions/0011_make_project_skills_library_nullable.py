"""make project skills library nullable

Revision ID: 0011_make_project_skills_library_nullable
Revises: 0010_add_project_pcloud_path
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_make_project_skills_library_nullable"
down_revision = "0010_add_project_pcloud_path"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.alter_column(
        "ai_project_skills",
        "project_id",
        existing_type=sa.Integer(),
        nullable=True,
        schema=TARGET_SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "ai_project_skills",
        "project_id",
        existing_type=sa.Integer(),
        nullable=False,
        schema=TARGET_SCHEMA,
    )
