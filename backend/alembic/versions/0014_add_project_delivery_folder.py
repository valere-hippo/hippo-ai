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
    op.add_column("ai_projects", sa.Column("active_conversation_id", sa.Integer(), nullable=True), schema=TARGET_SCHEMA)
    op.add_column("ai_projects", sa.Column("source_scope", sa.Text(), nullable=True), schema=TARGET_SCHEMA)
    op.create_foreign_key(
        "fk_ai_projects_active_conversation_id_ai_conversations",
        "ai_projects",
        "ai_conversations",
        ["active_conversation_id"],
        ["id"],
        source_schema=TARGET_SCHEMA,
        referent_schema=TARGET_SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("ai_projects", "source_scope", schema=TARGET_SCHEMA)
    op.drop_constraint("fk_ai_projects_active_conversation_id_ai_conversations", "ai_projects", schema=TARGET_SCHEMA, type_="foreignkey")
    op.drop_column("ai_projects", "active_conversation_id", schema=TARGET_SCHEMA)
    op.drop_column("ai_projects", "delivery_folder", schema=TARGET_SCHEMA)
