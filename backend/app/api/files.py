import json

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text

from app.api.dependencies import get_current_user, DbSession
from app.models.user import UserRole
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.services.project_storage import (
    has_s3_storage,
    list_project_files,
    project_bucket_name,
    project_object_prefix,
    read_project_file,
    store_project_file,
)

router = APIRouter(prefix="/files", tags=["files"]) 


@router.post("/projects/{project_id}/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(project_id: int, db: DbSession, current_user=Depends(get_current_user), file: UploadFile = File(...)):
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
    storage_result = store_project_file(project, file.filename, content, file.content_type)

    # attempt to auto-index text files (txt, md)
    try:
        from app.core.config import settings
        _, ext = file.filename.lower().rsplit(".", 1) if "." in file.filename else ("", "")
        if f".{ext}" in ['.txt', '.md', '.markdown'] and getattr(settings, 'hippo_embedding_url', None):
            text_content = content.decode('utf-8', errors='ignore')
            # call embedding API
            import httpx, json
            r = httpx.post(settings.hippo_embedding_url.rstrip('/') + '/embeddings', json={'texts':[text_content]}, timeout=20.0)
            if r.status_code == 200:
                data = r.json()
                emb = None
                if isinstance(data, dict) and 'embeddings' in data:
                    emb = data['embeddings'][0]
                elif isinstance(data, list):
                    emb = data[0]
                if emb is not None:
                    # insert into embeddings table (assumes pgvector column 'embedding')
                    try:
                        async def _insert_embedding():
                            async with DbSession() as session:
                                await session.execute(
                                    text("INSERT INTO embeddings (project_id, text, embedding, metadata) VALUES (:project_id, :text, :embedding, :metadata)"),
                                    {"project_id": project_id, "text": text_content, "embedding": emb, "metadata": json.dumps({"filename": file.filename})}
                                )
                                await session.commit()
                        import asyncio
                        asyncio.create_task(_insert_embedding())
                    except Exception:
                        pass
    except Exception:
        pass

    return {"filename": storage_result["filename"], "storage": storage_result["storage"], "bucket": storage_result.get("bucket"), "path": storage_result.get("path"), "key": storage_result.get("key")}


@router.get("/projects/{project_id}")
async def list_project_files(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
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
        "provider": "s3" if has_s3_storage() else "local",
        "bucket": project_bucket_name(project) if has_s3_storage() else None,
        "key_prefix": project_object_prefix(project) if has_s3_storage() else None,
        "watched_folder": project.watched_folder,
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
