"""create project skills

Revision ID: 0006_create_project_skills
Revises: 0005_move_app_tables_to_hippoai_schema
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_create_project_skills"
down_revision = "0005_move_app_tables_to_hippoai_schema"
branch_labels = None
depend_on = None


def upgrade():
    op.create_table(
        "ai_project_skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["hippoai.ai_projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ai_project_skills_project_id_idx", "ai_project_skills", ["project_id"], unique=False)
    op.create_index("ai_project_skills_name_project_idx", "ai_project_skills", ["project_id", "name"], unique=True)


def downgrade():
    op.drop_index("ai_project_skills_name_project_idx", table_name="ai_project_skills")
    op.drop_index("ai_project_skills_project_id_idx", table_name="ai_project_skills")
    op.drop_table("ai_project_skills")
