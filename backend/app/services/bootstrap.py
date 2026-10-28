from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User, UserRole


async def ensure_bootstrap_admin(session: AsyncSession) -> bool:
    email = settings.bootstrap_admin_email.lower().strip()
    existing = await session.execute(select(User).where(User.email == email))
    admin = existing.scalar_one_or_none()
    desired_full_name = settings.bootstrap_admin_full_name.strip()
    desired_password_hash = hash_password(settings.bootstrap_admin_password)

    if admin is not None:
        changed = False
        if admin.full_name != desired_full_name:
            admin.full_name = desired_full_name
            changed = True
        if admin.password_hash != desired_password_hash:
            admin.password_hash = desired_password_hash
            changed = True
        if admin.role != UserRole.ADMIN:
            admin.role = UserRole.ADMIN
            changed = True
        if not admin.is_active:
            admin.is_active = True
            changed = True
        if changed:
            await session.commit()
            await session.refresh(admin)
        return False

    admin = User(
        email=email,
        full_name=desired_full_name,
        password_hash=desired_password_hash,
        role=UserRole.ADMIN,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return True
