"""allow shared skills and embeddings

Revision ID: 0006_shared_skills_and_embeddings
Revises: 0005_move_app_tables_to_hippoai_schema
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_shared_skills_and_embeddings"
down_revision = "0005_move_app_tables_to_hippoai_schema"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.alter_column(
        "ai_project_skills",
        "project_id",
        schema=TARGET_SCHEMA,
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "ai_embeddings",
        "project_id",
        schema=TARGET_SCHEMA,
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "ai_embeddings",
        "project_id",
        schema=TARGET_SCHEMA,
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "ai_project_skills",
        "project_id",
        schema=TARGET_SCHEMA,
        existing_type=sa.Integer(),
        nullable=False,
    )
