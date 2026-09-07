from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update

from app.api.dependencies import DbSession, get_current_user
from app.models.project import Project
from app.models.user import UserRole
from app.services.permissions import has_project_permission
from app.models.permission import PermissionLevel

router = APIRouter(prefix="/projects", tags=["project-folders"]) 

@router.post('/{project_id}/folder')
async def set_project_folder(project_id: int, payload: dict, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail='Projekt nicht gefunden.')
    if not (current_user.role == UserRole.ADMIN or project.owner_id == current_user.id):
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    folder = str(payload.get('folder') or '').strip()
    if not folder:
        raise HTTPException(status_code=400, detail='Bitte einen Ordner auswählen.')
    path = Path(folder).expanduser()
    if not path.is_absolute():
        raise HTTPException(status_code=400, detail='Bitte einen absoluten Ordnerpfad auswählen.')
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail='Bitte einen gültigen Ordner auswählen.')
    await db.execute(update(Project).where(Project.id == project_id).values(watched_folder=str(path.resolve())))
    await db.commit()
    return {'project_id': project_id, 'folder': str(path.resolve())}

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
