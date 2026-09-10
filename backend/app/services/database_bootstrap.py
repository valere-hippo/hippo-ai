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
                f'ALTER TABLE IF EXISTS "{settings.postgres_schema}"."ai_project_skills" '
                'ALTER COLUMN project_id DROP NOT NULL'
            )
        )
