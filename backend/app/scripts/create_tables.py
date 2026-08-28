import asyncio

from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.models import Base

async def main():
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.postgres_schema}"'))
        await conn.run_sync(Base.metadata.create_all)

if __name__ == '__main__':
    asyncio.run(main())
    print('created tables')
