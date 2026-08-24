import os
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from typing import List
from sqlalchemy import select

from app.api.dependencies import get_current_user, DbSession
from app.models.user import UserRole
from app.models.project import Project
from app.models.permission import PermissionLevel

UPLOAD_ROOT = "/app/uploads"

router = APIRouter(prefix="/files", tags=["files"]) 


def ensure_project_dir(project_id: int) -> str:
    path = os.path.join(UPLOAD_ROOT, str(project_id))
    os.makedirs(path, exist_ok=True)
    return path


@router.post("/projects/{project_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(project_id: int, db: DbSession, current_user=Depends(get_current_user), file: UploadFile = File(...)):
    # Verify project access
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # check permission: WRITE required
    from app.services.permissions import has_project_permission
    has = await has_project_permission(db, current_user, project, PermissionLevel.WRITE)
    if not has:
        raise HTTPException(status_code=403, detail="Forbidden")

    dest_dir = ensure_project_dir(project_id)
    dest_path = os.path.join(dest_dir, file.filename)
    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)
    return {"filename": file.filename, "path": dest_path}


@router.get("/projects/{project_id}")
async def list_project_files(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    dir_path = os.path.join(UPLOAD_ROOT, str(project_id))
    if not os.path.exists(dir_path):
        return []
    files = [f for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))]
    return files
