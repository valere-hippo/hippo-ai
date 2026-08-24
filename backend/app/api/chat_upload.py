from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
import os
from sqlalchemy import insert, select

from app.api.dependencies import DbSession, get_current_user
from app.models.project import Project
from app.models.user import UserRole
from app.models.chat import ChatMessage
from app.services.permissions import has_project_permission

UPLOAD_ROOT = "/app/uploads"

router = APIRouter(prefix="/chat", tags=["chat-upload"]) 

@router.post('/upload', status_code=status.HTTP_201_CREATED)
async def upload_and_attach(project_id: int, file: UploadFile = File(...), db: DbSession = Depends(), current_user=Depends(get_current_user)):
    # verify project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail='Project not found')
    allowed = await has_project_permission(db, current_user, project, level=__import__('app.models.permission', fromlist=['PermissionLevel']).PermissionLevel.WRITE)
    if not allowed:
        raise HTTPException(status_code=403, detail='Forbidden')
    # save file
    dest_dir = os.path.join(UPLOAD_ROOT, str(project_id))
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, file.filename)
    with open(dest_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    # create chat message referencing file
    await db.execute(insert(ChatMessage).values(conversation_id=0, user_id=current_user.id, role='user', content=f"file:{dest_path}"))
    await db.commit()
    return {'filename': file.filename, 'path': dest_path}
