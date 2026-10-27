from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.models import Base


async def ensure_database_schema_and_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.postgres_schema}"'))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_projects" '
                'ADD COLUMN IF NOT EXISTS pcloud_path VARCHAR(1000)'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_projects" '
                'ADD COLUMN IF NOT EXISTS delivery_folder VARCHAR(1000)'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_projects" '
                'ADD COLUMN IF NOT EXISTS active_conversation_id INTEGER'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_projects" '
                'ADD COLUMN IF NOT EXISTS default_profile_id INTEGER'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_projects" '
                'ADD COLUMN IF NOT EXISTS source_scope TEXT'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_projects" '
                'ADD COLUMN IF NOT EXISTS pcloud_folder_id BIGINT'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_projects" '
                'ALTER COLUMN pcloud_folder_id TYPE BIGINT USING pcloud_folder_id::BIGINT'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_project_skills" '
                'ALTER COLUMN project_id DROP NOT NULL'
            )
        )
        await conn.execute(
            text(
                f'CREATE TABLE IF NOT EXISTS "{settings.postgres_schema}"."ai_chat_profiles" ('
                'id SERIAL PRIMARY KEY, '
                'owner_id INTEGER NOT NULL, '
                'project_id INTEGER NULL, '
                'name VARCHAR(120) NOT NULL, '
                'chat_bot_id VARCHAR(120) NOT NULL, '
                'description TEXT NULL, '
                'memory_notes TEXT NULL, '
                'system_prompt TEXT NULL, '
                'memory_namespace VARCHAR(120) NULL, '
                'share_scope VARCHAR(20) NOT NULL DEFAULT ''private'', '
                'model_provider VARCHAR(40) NULL, '
                'model_name VARCHAR(120) NULL, '
                'allow_shared_skills BOOLEAN NOT NULL DEFAULT TRUE, '
                'allow_shared_tools BOOLEAN NOT NULL DEFAULT TRUE, '
                'is_active BOOLEAN NOT NULL DEFAULT TRUE, '
                'created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(), '
                'updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()'
                ')'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_conversations" '
                'ADD COLUMN IF NOT EXISTS profile_id INTEGER'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_chat_profiles" '
                'ADD COLUMN IF NOT EXISTS memory_notes TEXT'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_chat_profiles" '
                'ADD COLUMN IF NOT EXISTS share_scope VARCHAR(20) NOT NULL DEFAULT ''private'''
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_project_skills" '
                'ADD COLUMN IF NOT EXISTS source_project_id INTEGER'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_tools" '
                'ADD COLUMN IF NOT EXISTS project_id INTEGER'
            )
        )
        await conn.execute(
            text(
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_tools" '
                'ADD COLUMN IF NOT EXISTS source_project_id INTEGER'
            )
        )
