from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import insert, select

from app.api.dependencies import DbSession, get_current_user
from app.models.permission import ProjectPermission, PermissionLevel
from app.models.user import UserRole
from app.schemas.permission import PermissionCreate, PermissionResponse

router = APIRouter(prefix="/permissions", tags=["permissions"])

@router.post('/', response_model=PermissionResponse, status_code=status.HTTP_201_CREATED)
async def grant_permission(payload: PermissionCreate, db: DbSession, current_user=Depends(get_current_user)):
    # only admins can grant
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    level = payload.level.upper()
    try:
        lvl = PermissionLevel[level]
    except KeyError:
        raise HTTPException(status_code=400, detail='Ungültige Berechtigungsstufe.')

    stmt = insert(ProjectPermission).values(user_id=payload.user_id, project_id=payload.project_id, level=lvl)
    result = await db.execute(stmt.returning(ProjectPermission))
    await db.commit()
    perm = result.scalar_one()
    return perm

@router.get('/project/{project_id}')
async def list_permissions(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    # admins or project owners
    result = await db.execute(select(ProjectPermission).where(ProjectPermission.project_id == project_id))
    perms = result.scalars().all()
    return perms
