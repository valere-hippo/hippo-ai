"""add project delivery folder

Revision ID: 0014_add_project_delivery_folder
Revises: 0013_expand_project_pcloud_folder_id_bigint
Create Date: 2026-09-25
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_add_project_delivery_folder"
down_revision = "0013_expand_project_pcloud_folder_id_bigint"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.add_column("ai_projects", sa.Column("delivery_folder", sa.String(length=1000), nullable=True), schema=TARGET_SCHEMA)


def downgrade() -> None:
    op.drop_column("ai_projects", "delivery_folder", schema=TARGET_SCHEMA)
