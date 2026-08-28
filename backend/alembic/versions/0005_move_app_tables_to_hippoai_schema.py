"""move app tables to hippoai schema

Revision ID: 0005_move_app_tables_to_hippoai_schema
Revises: 0004_prefix_ai_tables
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_move_app_tables_to_hippoai_schema"
down_revision = "0004_prefix_ai_tables"
branch_labels = None
depends_on = None


TARGET_SCHEMA = "hippoai"
APP_TABLES = (
    "ai_users",
    "ai_projects",
    "ai_project_permissions",
    "ai_conversations",
    "ai_chat_messages",
    "ai_embeddings",
)


def _table_names(bind, schema: str) -> set[str]:
    return set(sa.inspect(bind).get_table_names(schema=schema))


def _sequence_names(bind, schema: str) -> set[str]:
    return set(sa.inspect(bind).get_sequence_names(schema=schema))


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{TARGET_SCHEMA}"'))

    public_tables = _table_names(bind, "public")
    hippoai_tables = _table_names(bind, TARGET_SCHEMA)
    public_sequences = _sequence_names(bind, "public")
    hippoai_sequences = _sequence_names(bind, TARGET_SCHEMA)

    for table_name in APP_TABLES:
        if table_name in public_tables and table_name not in hippoai_tables:
            op.execute(sa.text(f'ALTER TABLE public."{table_name}" SET SCHEMA "{TARGET_SCHEMA}"'))

    for sequence_name in public_sequences:
        if sequence_name.startswith("ai_") and sequence_name not in hippoai_sequences:
            op.execute(sa.text(f'ALTER SEQUENCE public."{sequence_name}" SET SCHEMA "{TARGET_SCHEMA}"'))


def downgrade() -> None:
    bind = op.get_bind()

    hippoai_tables = _table_names(bind, TARGET_SCHEMA)
    public_tables = _table_names(bind, "public")
    hippoai_sequences = _sequence_names(bind, TARGET_SCHEMA)
    public_sequences = _sequence_names(bind, "public")

    for table_name in reversed(APP_TABLES):
        if table_name in hippoai_tables and table_name not in public_tables:
            op.execute(sa.text(f'ALTER TABLE "{TARGET_SCHEMA}"."{table_name}" SET SCHEMA public'))

    for sequence_name in reversed(sorted(hippoai_sequences)):
        if sequence_name.startswith("ai_") and sequence_name not in public_sequences:
            op.execute(sa.text(f'ALTER SEQUENCE "{TARGET_SCHEMA}"."{sequence_name}" SET SCHEMA public'))
