from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update

from app.api.dependencies import DbSession, get_current_user
from app.models.project import Project
from app.services.permissions import has_project_permission
from app.models.permission import PermissionLevel

router = APIRouter(prefix="/projects", tags=["project-folders"]) 

@router.post('/{project_id}/folder')
async def set_project_folder(project_id: int, payload: dict, db: DbSession, current_user=Depends(get_current_user)):
    # only owner or admin
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail='Projekt nicht gefunden.')
    if not (current_user.role == 'ADMIN' or project.owner_id == current_user.id):
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    folder = payload.get('folder')
    await db.execute(update(Project).where(Project.id == project_id).values(watched_folder=folder))
    await db.commit()
    return {'project_id': project_id, 'folder': folder}

@router.get('/{project_id}/folder')
async def get_project_folder(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail='Projekt nicht gefunden.')
    # check permission
    allowed = await has_project_permission(db, current_user, project, PermissionLevel.READ)
    if not allowed:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    return {'project_id': project_id, 'folder': project.watched_folder}
