import base64
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.dependencies import get_current_user, DbSession
from app.models.user import UserRole
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.services.project_storage import (
    can_use_s3_storage,
    clear_project_storage,
    delete_project_file,
    has_s3_storage,
    list_project_files,
    project_bucket_name,
    project_object_prefix,
    read_project_file,
    store_project_file,
)

router = APIRouter(prefix="/files", tags=["files"]) 


class ProjectSourceUpload(BaseModel):
    source_folder: str = Field(min_length=1, max_length=1000)
    relative_path: str = Field(min_length=1, max_length=2000)
    filename: str = Field(min_length=1, max_length=1000)
    content_base64: str = Field(min_length=1)
    content_type: str | None = Field(default=None, max_length=200)


@router.post("/projects/{project_id}/source-upload", status_code=status.HTTP_201_CREATED)
async def upload_project_source_file(project_id: int, payload: ProjectSourceUpload, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")

    from app.services.permissions import has_project_permission
    has = await has_project_permission(db, current_user, project, PermissionLevel.WRITE)
    if not has:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    try:
        content = base64.b64decode(payload.content_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige Dateidaten: {exc}")

    storage_path = f"sources/{payload.source_folder.strip().strip('/')}/{payload.relative_path.strip().lstrip('/')}"
    storage_result = store_project_file(
        project,
        payload.filename,
        content,
        payload.content_type,
        storage_path=storage_path,
    )
    return {
        "filename": storage_result["filename"],
        "storage": storage_result["storage"],
        "bucket": storage_result.get("bucket"),
        "path": storage_result.get("path"),
        "key": storage_result.get("key"),
    }


@router.post("/projects/{project_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(project_id: int, db: DbSession, current_user=Depends(get_current_user), file: UploadFile = File(...), storage_path: str | None = Form(None)):
    # Verify project access
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")

    # check permission: WRITE required
    from app.services.permissions import has_project_permission
    has = await has_project_permission(db, current_user, project, PermissionLevel.WRITE)
    if not has:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    content = await file.read()
    storage_result = store_project_file(project, file.filename, content, file.content_type, storage_path=storage_path)

    # attempt to auto-index text files (txt, md)
    # embeddings have been removed from Hippo AI; files are stored directly only.

    return {"filename": storage_result["filename"], "storage": storage_result["storage"], "bucket": storage_result.get("bucket"), "path": storage_result.get("path"), "key": storage_result.get("key")}


@router.get("/projects/{project_id}")
async def get_project_files(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")
    from app.services.permissions import has_project_permission
    allowed = await has_project_permission(db, current_user, project, PermissionLevel.READ)
    if not allowed:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")
    return [
        {
            "filename": item.filename,
            "size": item.size,
            "modified_at": item.modified_at.isoformat() if item.modified_at else None,
            "storage": item.storage,
        }
        for item in list_project_files(project)
    ]


@router.get("/projects/{project_id}/storage")
async def get_project_storage(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")
    from app.services.permissions import has_project_permission
    allowed = await has_project_permission(db, current_user, project, PermissionLevel.READ)
    if not allowed:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")
    files = list_project_files(project)
    return {
        "project_id": project.id,
        "project_name": project.name,
        "provider": "s3" if can_use_s3_storage() else "local",
        "bucket": project_bucket_name(project) if can_use_s3_storage() else None,
        "key_prefix": project_object_prefix(project) if can_use_s3_storage() else None,
        "watched_folder": project.watched_folder,
        "delivery_folder": getattr(project, "delivery_folder", None),
        "files": [
            {
                "filename": item.filename,
                "size": item.size,
                "modified_at": item.modified_at.isoformat() if item.modified_at else None,
                "storage": item.storage,
            }
            for item in files
        ],
    }


@router.get("/projects/{project_id}/download/{filename}")
async def download_project_file(project_id: int, filename: str, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")
    from app.services.permissions import has_project_permission
    allowed = await has_project_permission(db, current_user, project, PermissionLevel.READ)
    if not allowed:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")
    try:
        content, content_type, storage = read_project_file(project, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "X-Storage-Backend": storage}
    return StreamingResponse(iter([content]), media_type=content_type, headers=headers)


@router.delete("/projects/{project_id}/storage")
async def clear_project_storage_endpoint(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")

    from app.services.permissions import has_project_permission
    allowed = await has_project_permission(db, current_user, project, PermissionLevel.ADMIN)
    if not allowed:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    deleted = clear_project_storage(project)
    return {
        "ok": True,
        "project_id": project.id,
        "deleted_remote": deleted["deleted_remote"],
        "deleted_local": deleted["deleted_local"],
        "provider": "s3" if can_use_s3_storage() else "local",
    }


@router.delete("/projects/{project_id}/storage/{filename}")
async def delete_project_file_endpoint(project_id: int, filename: str, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")

    from app.services.permissions import has_project_permission
    allowed = await has_project_permission(db, current_user, project, PermissionLevel.ADMIN)
    if not allowed:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    existing_files = {item.filename for item in list_project_files(project)}
    if filename not in existing_files:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden.")

    deleted = delete_project_file(project, filename)

    return {
        "ok": True,
        "project_id": project.id,
        "filename": deleted["filename"],
        "deleted_remote": deleted["deleted_remote"],
        "deleted_local": deleted["deleted_local"],
        "provider": "s3" if can_use_s3_storage() else "local",
    }
