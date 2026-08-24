from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import ProjectPermission, PermissionLevel


async def get_permission(session: AsyncSession, user_id: int, project_id: int):
    q = select(ProjectPermission).where(
        ProjectPermission.user_id == user_id,
        ProjectPermission.project_id == project_id,
        ProjectPermission.is_active == True,
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()


def level_value(level: PermissionLevel) -> int:
    order = {PermissionLevel.READ: 1, PermissionLevel.WRITE: 2, PermissionLevel.ADMIN: 3}
    return order.get(level, 0)


async def has_project_permission(session: AsyncSession, user, project, required: PermissionLevel):
    # admins bypass
    if getattr(user, 'role', None) and str(user.role) == 'ADMIN':
        return True
    # owner bypass
    if getattr(project, 'owner_id', None) == getattr(user, 'id', None):
        return True
    perm = await get_permission(session, user.id, project.id)
    if perm is None:
        return False
    return level_value(perm.level) >= level_value(required)
