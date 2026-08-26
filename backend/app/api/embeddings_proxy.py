from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.dependencies import get_current_user
from app.core.config import settings
import httpx

router = APIRouter(prefix="/embeddings-proxy", tags=["embeddings-proxy"]) 

class EmbeddingStoreItem(BaseModel):
    text: str
    metadata: dict | None = None

class EmbeddingStoreRequest(BaseModel):
    project_id: int
    items: list[EmbeddingStoreItem]

class EmbeddingSearchRequest(BaseModel):
    project_id: int
    query: str
    limit: int = 5
    min_score: float = 0.0


@router.post('/store')
async def store_embeddings(payload: EmbeddingStoreRequest, current_user = Depends(get_current_user)):
    if not settings.hippo_embedding_url:
        raise HTTPException(status_code=503, detail='Der Embedding-Dienst ist nicht konfiguriert.')
    headers = {"Content-Type": "application/json"}
    if settings.hippo_embedding_key:
        headers["Authorization"] = f"Bearer {settings.hippo_embedding_key}"
    body = {"project_id": payload.project_id, "items": [item.dict() for item in payload.items]}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(settings.hippo_embedding_url.rstrip('/') + '/embeddings/store', json=body, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Fehler beim Speichern im Embedding: {e}')


@router.post('/search')
async def search_embeddings(payload: EmbeddingSearchRequest, current_user = Depends(get_current_user)):
    if not settings.hippo_embedding_url:
        raise HTTPException(status_code=503, detail='Der Embedding-Dienst ist nicht konfiguriert.')
    headers = {"Content-Type": "application/json"}
    if settings.hippo_embedding_key:
        headers["Authorization"] = f"Bearer {settings.hippo_embedding_key}"
    body = {"project_id": payload.project_id, "query": payload.query, "limit": payload.limit, "min_score": payload.min_score}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(settings.hippo_embedding_url.rstrip('/') + '/embeddings/search', json=body, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Fehler bei der Embedding-Suche: {e}')
