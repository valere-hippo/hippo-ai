from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User, UserRole


async def ensure_bootstrap_admin(session: AsyncSession) -> bool:
    email = settings.bootstrap_admin_email.lower().strip()
    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        return False

    admin = User(
        email=email,
        full_name=settings.bootstrap_admin_full_name.strip(),
        password_hash=hash_password(settings.bootstrap_admin_password),
        role=UserRole.ADMIN,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return True
