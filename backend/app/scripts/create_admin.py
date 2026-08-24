import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole
from app.core.security import hash_password

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email == 'admin@example.com'))
        user = result.scalar_one_or_none()
        if user:
            print('admin already exists')
            return
        admin = User(email='admin@example.com', full_name='Admin', password_hash=hash_password('password123'), role=UserRole.ADMIN)
        session.add(admin)
        await session.commit()
        print('admin created')

if __name__ == '__main__':
    asyncio.run(main())
