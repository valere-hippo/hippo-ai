import asyncio

from app.db.session import AsyncSessionLocal
from app.services.bootstrap import ensure_bootstrap_admin

async def main():
    async with AsyncSessionLocal() as session:
        created = await ensure_bootstrap_admin(session)
        print('admin created' if created else 'admin already exists')

if __name__ == '__main__':
    asyncio.run(main())
