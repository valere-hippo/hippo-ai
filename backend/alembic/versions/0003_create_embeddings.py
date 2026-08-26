"""create embeddings table with pgvector

Revision ID: 0003_create_embeddings
Revises: 0002_permissions_chat
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa

revision = '0003_create_embeddings'
down_revision = '0002_permissions_chat'
branch_labels = None
depend_on = None


def upgrade():
    # create vector extension if not exists
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # create embeddings table if not exists
    op.execute("""
    CREATE TABLE IF NOT EXISTS embeddings (
        id BIGSERIAL PRIMARY KEY,
        project_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        embedding vector(1024) NOT NULL,
        metadata JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ DEFAULT now()
    );
    """)

    # create hnsw index for pgvector cosine search
    op.execute("CREATE INDEX IF NOT EXISTS embeddings_embedding_hnsw ON embeddings USING hnsw (embedding vector_cosine_ops);")
    op.execute("CREATE INDEX IF NOT EXISTS embeddings_project_id_idx ON embeddings (project_id);")
    op.execute("CREATE INDEX IF NOT EXISTS embeddings_metadata_idx ON embeddings USING gin (metadata);")


def downgrade():
    op.execute("DROP INDEX IF EXISTS embeddings_metadata_idx;")
    op.execute("DROP INDEX IF EXISTS embeddings_project_id_idx;")
    op.execute("DROP INDEX IF EXISTS embeddings_embedding_hnsw;")
    op.execute("DROP TABLE IF EXISTS embeddings;")
