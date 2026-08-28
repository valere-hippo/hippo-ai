import asyncio

from app.db.session import engine
from app.services.database_bootstrap import ensure_database_schema_and_tables

async def main():
    await ensure_database_schema_and_tables(engine)

if __name__ == '__main__':
    asyncio.run(main())
    print('created tables')
