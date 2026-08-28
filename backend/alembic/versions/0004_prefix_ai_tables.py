"""prefix all tables with ai_

Revision ID: 0004_prefix_ai_tables
Revises: 0003_create_embeddings
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_prefix_ai_tables"
down_revision = "0003_create_embeddings"
branch_labels = None
depend_on = None


TABLE_RENAMES = [
    ("users", "ai_users"),
    ("projects", "ai_projects"),
    ("project_permissions", "ai_project_permissions"),
    ("conversations", "ai_conversations"),
    ("chat_messages", "ai_chat_messages"),
    ("embeddings", "ai_embeddings"),
]

INDEX_RENAMES = [
    ("ai_users", "ix_users_email", "ix_ai_users_email"),
    ("ai_embeddings", "embeddings_embedding_hnsw", "ai_embeddings_embedding_hnsw"),
    ("ai_embeddings", "embeddings_project_id_idx", "ai_embeddings_project_id_idx"),
    ("ai_embeddings", "embeddings_metadata_idx", "ai_embeddings_metadata_idx"),
]


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    for old_name, new_name in TABLE_RENAMES:
        if old_name in table_names and new_name not in table_names:
            op.rename_table(old_name, new_name)

    bind = op.get_bind()
    for table_name, old_index, new_index in INDEX_RENAMES:
        if table_name not in _table_names(bind):
            continue
        index_names = _index_names(bind, table_name)
        if old_index in index_names and new_index not in index_names:
            op.execute(sa.text(f'ALTER INDEX "{old_index}" RENAME TO "{new_index}"'))


def downgrade() -> None:
    bind = op.get_bind()
    table_names = _table_names(bind)

    for old_name, new_name in reversed(TABLE_RENAMES):
        if new_name in table_names and old_name not in table_names:
            op.rename_table(new_name, old_name)

    bind = op.get_bind()
    for table_name, old_index, new_index in reversed(INDEX_RENAMES):
        if table_name not in _table_names(bind):
            continue
        index_names = _index_names(bind, table_name)
        if new_index in index_names and old_index not in index_names:
            op.execute(sa.text(f'ALTER INDEX "{new_index}" RENAME TO "{old_index}"'))
