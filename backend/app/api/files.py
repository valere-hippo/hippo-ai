import os
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy import select, text

from app.api.dependencies import get_current_user, DbSession
from app.core.config import settings
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
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")

    # check permission: WRITE required
    from app.services.permissions import has_project_permission
    has = await has_project_permission(db, current_user, project, PermissionLevel.WRITE)
    if not has:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    dest_dir = ensure_project_dir(project_id)
    dest_path = os.path.join(dest_dir, file.filename)
    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # attempt to auto-index text files (txt, md)
    try:
        _, ext = os.path.splitext(file.filename.lower())
        if ext in ['.txt', '.md', '.markdown'] and getattr(settings, 'hippo_embedding_url', None):
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

    return {"filename": file.filename, "path": dest_path}


@router.get("/projects/{project_id}")
async def list_project_files(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    dir_path = os.path.join(UPLOAD_ROOT, str(project_id))
    if not os.path.exists(dir_path):
        return []
    files = [f for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))]
    return files
