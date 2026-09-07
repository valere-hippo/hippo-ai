from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.api.dependencies import DbSession, get_current_user
from app.core.config import settings

router = APIRouter(prefix="/search", tags=["search"])
EMBEDDINGS_TABLE = f"{settings.postgres_schema}.ai_embeddings"


class SearchRequest(BaseModel):
    query: str
    project_id: int | None = None
    top_k: int = 5
    offset: int = 0


class SearchResultItem(BaseModel):
    id: int
    text: str
    score: float
    metadata: dict | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    next_offset: int | None = None


@router.post("/", response_model=SearchResponse)
async def semantic_search(payload: SearchRequest, db: DbSession, user=Depends(get_current_user)):
    if not settings.hippo_embedding_url:
        raise HTTPException(status_code=503, detail="Embedding service URL not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(settings.hippo_embedding_url.rstrip("/") + "/embeddings", json={"texts": [payload.query]})
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "embeddings" in data:
                emb = data["embeddings"][0]
            elif isinstance(data, list):
                emb = data[0]
            else:
                raise ValueError("Unexpected embedding response")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Embedding error: {exc}") from exc

    sql = text(
        "SELECT id, text, metadata, 1 - (embedding <=> (:vec)::vector) AS similarity "
        f"FROM {EMBEDDINGS_TABLE} "
        + (
            "WHERE (project_id = :project_id OR project_id IS NULL) "
            if payload.project_id is not None
            else "WHERE project_id IS NULL "
        )
        + "ORDER BY embedding <=> (:vec)::vector LIMIT :k OFFSET :offset"
    )

    params = {"vec": emb, "k": payload.top_k, "offset": payload.offset}
    if payload.project_id is not None:
        params["project_id"] = payload.project_id

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
        results = [
            {"id": row[0], "text": row[1], "score": float(row[3]), "metadata": row[2]}
            for row in rows
        ]
        next_offset = payload.offset + payload.top_k if len(rows) == payload.top_k else None
        return {"results": results, "next_offset": next_offset}
    except Exception as exc:
        err_msg = str(exc)
        if (
            "UndefinedTableError" in err_msg
            or 'relation "ai_embeddings" does not exist' in err_msg
            or 'relation "embeddings" does not exist' in err_msg
        ):
            raise HTTPException(
                status_code=503,
                detail=f'Embeddings table not found in schema "{settings.postgres_schema}" or pgvector not installed. Run migrations and install the pgvector extension.',
            ) from exc
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
