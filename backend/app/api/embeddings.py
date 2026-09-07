from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, text as sql_text

from app.api.dependencies import DbSession, get_current_user
from app.core.config import settings
from app.models.project import Project
from app.models.user import User
from app.services.permissions import has_project_permission
from app.models.permission import PermissionLevel

router = APIRouter(prefix="/embeddings", tags=["embeddings"])
library_router = APIRouter(prefix="/embeddings", tags=["embeddings-library"])
EMBEDDINGS_TABLE = f"{settings.postgres_schema}.ai_embeddings"


class EmbeddingRequest(BaseModel):
    texts: list[str]


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]


class EmbeddingStoreRequest(BaseModel):
    text: str
    project_id: int | None = None
    metadata: dict[str, Any] | None = None


class EmbeddingLibraryItem(BaseModel):
    id: int
    project_id: int | None
    text: str
    metadata: dict[str, Any] | None
    created_at: str


async def _embedding_vector(text: str) -> list[float]:
    if not settings.hippo_embedding_url:
        raise HTTPException(status_code=503, detail="Der Embedding-Dienst ist nicht konfiguriert.")

    headers = {"Content-Type": "application/json"}
    if settings.hippo_embedding_key:
        headers["Authorization"] = f"Bearer {settings.hippo_embedding_key}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            settings.hippo_embedding_url.rstrip("/") + "/embeddings",
            json={"texts": [text]},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    if isinstance(data, dict) and "embeddings" in data:
        embeddings = data["embeddings"]
        if isinstance(embeddings, list) and embeddings:
            return embeddings[0]
    if isinstance(data, list) and data:
        return data[0]

    raise HTTPException(status_code=502, detail="Unerwartete Antwort des Embedding-Dienstes.")


async def _store_embedding_text(db: DbSession, project_id: int | None, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    vector = await _embedding_vector(content)
    sql = (
        f"INSERT INTO {EMBEDDINGS_TABLE} (project_id, text, embedding, metadata) "
        "VALUES (:project_id, :text, :embedding, :metadata) "
        "RETURNING id, project_id, text, metadata, created_at"
    )
    try:
        result = await db.execute(
            sql_text(sql),
            {
                "project_id": project_id,
                "text": content,
                "embedding": vector,
                "metadata": metadata or {},
            },
        )
        await db.commit()
        row = result.mappings().one()
        return dict(row)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Fehler beim Speichern im Embedding-Store: {exc}") from exc


@router.post("/", response_model=EmbeddingResponse)
async def create_embeddings(payload: EmbeddingRequest, current_user=Depends(get_current_user)):
    if not settings.hippo_embedding_url:
        raise HTTPException(status_code=503, detail="Der Embedding-Dienst ist nicht konfiguriert.")

    headers = {"Content-Type": "application/json"}
    if settings.hippo_embedding_key:
        headers["Authorization"] = f"Bearer {settings.hippo_embedding_key}"
    body = {"texts": payload.texts}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(settings.hippo_embedding_url.rstrip('/') + '/embeddings', json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and 'embeddings' in data:
                return {'embeddings': data['embeddings']}
            if isinstance(data, list):
                return {'embeddings': data}
            raise HTTPException(status_code=502, detail='Unerwartete Antwort des Embedding-Dienstes.')
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Fehler des Embedding-Dienstes: {e}')


@library_router.get("/library", response_model=list[EmbeddingLibraryItem])
async def list_embedding_library(db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")

    sql = sql_text(
        f"SELECT id, project_id, text, metadata, created_at "
        f"FROM {EMBEDDINGS_TABLE} "
        "WHERE project_id IS NULL "
        "ORDER BY created_at DESC "
        "LIMIT 100"
    )
    result = await db.execute(sql)
    rows = result.mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        created_at = row.get("created_at")
        items.append(
            {
                "id": int(row.get("id") or 0),
                "project_id": row.get("project_id"),
                "text": str(row.get("text") or ""),
                "metadata": row.get("metadata"),
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
            }
        )
    return items


@library_router.post("/library")
async def store_embedding_library_item(payload: EmbeddingStoreRequest, db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    text_value = (payload.text or "").strip()
    if not text_value:
        raise HTTPException(status_code=400, detail="Der Text darf nicht leer sein.")

    if payload.project_id is not None:
        project_result = await db.execute(select(Project).where(Project.id == payload.project_id))
        project = project_result.scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")
        allowed = await has_project_permission(db, current_user, project, PermissionLevel.WRITE)
        if not allowed:
            raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    metadata = {**(payload.metadata or {}), "source": (payload.metadata or {}).get("source", "manual")}
    await _store_embedding_text(db, payload.project_id, text_value, metadata)
    return {"ok": True, "project_id": payload.project_id}


@library_router.post("/library/upload")
async def upload_embedding_markdown(
    db: DbSession,
    file: UploadFile = File(...),
    project_id: int | None = Form(default=None),
    current_user: User = Depends(get_current_user),
):
    if current_user is None:
        raise HTTPException(status_code=401, detail="Nicht angemeldet.")
    if not (file.filename or "").lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="Bitte eine Markdown-Datei (.md) hochladen.")

    if project_id is not None:
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Projekt nicht gefunden.")
        allowed = await has_project_permission(db, current_user, project, PermissionLevel.WRITE)
        if not allowed:
            raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    raw = await file.read()
    text = raw.decode("utf-8", errors="ignore").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Die Markdown-Datei ist leer.")

    metadata = {
        "filename": file.filename or "embedding.md",
        "source": "markdown-upload",
    }
    await _store_embedding_text(db, project_id, text, metadata)
    return {"ok": True, "project_id": project_id, "filename": file.filename}
