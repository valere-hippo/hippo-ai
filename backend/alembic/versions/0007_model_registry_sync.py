"""sync model registry snapshots

Revision ID: 0007_model_registry_sync
Revises: 0006_shared_skills_and_embeddings
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_model_registry_sync"
down_revision = "0006_shared_skills_and_embeddings"
branch_labels = None
depends_on = None

TARGET_SCHEMA = "hippoai"


def upgrade() -> None:
    op.create_table(
        "ai_model_registry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("capability", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "source_url", "model_id", name="uq_ai_model_registry_provider_source_model"),
        schema=TARGET_SCHEMA,
    )
    op.create_index("ix_ai_model_registry_provider", "ai_model_registry", ["provider"], schema=TARGET_SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_ai_model_registry_provider", table_name="ai_model_registry", schema=TARGET_SCHEMA)
    op.drop_table("ai_model_registry", schema=TARGET_SCHEMA)
