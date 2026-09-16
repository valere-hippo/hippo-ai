"""expand project pcloud folder id to bigint

Revision ID: 0013_expand_project_pcloud_folder_id_bigint
Revises: 0012_add_project_pcloud_folder_id
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_expand_project_pcloud_folder_id_bigint"
down_revision = "0012_add_project_pcloud_folder_id"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.alter_column(
        "ai_projects",
        "pcloud_folder_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
        schema=TARGET_SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "ai_projects",
        "pcloud_folder_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        schema=TARGET_SCHEMA,
    )
