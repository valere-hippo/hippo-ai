from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import DbSession, get_current_user
from app.models.project import Project
from app.services.permissions import has_project_permission
from app.services.project_storage import store_project_file
from app.models.permission import PermissionLevel

router = APIRouter(prefix="/chat", tags=["chat-upload"]) 

@router.post('/upload', status_code=status.HTTP_201_CREATED)
async def upload_and_attach(project_id: int, file: UploadFile = File(...), db: DbSession = Depends(), current_user=Depends(get_current_user)):
    # verify project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail='Projekt nicht gefunden.')
    allowed = await has_project_permission(db, current_user, project, level=PermissionLevel.WRITE)
    if not allowed:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    content = await file.read()
    storage = store_project_file(project, file.filename, content, file.content_type)
    return storage
