from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import DbSession, get_current_user

router = APIRouter(prefix="/search", tags=["search"])


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
    raise HTTPException(
        status_code=503,
        detail="Semantische Suche über Embeddings wurde entfernt. Nutze Skills, Tools oder die normale Chat-Suche.",
    )
