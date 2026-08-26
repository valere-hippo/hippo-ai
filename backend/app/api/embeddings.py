from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.dependencies import get_current_user
from app.core.config import settings
import httpx

router = APIRouter(prefix="/embeddings", tags=["embeddings"]) 

class EmbeddingRequest(BaseModel):
    texts: list[str]

class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]


@router.post('/', response_model=EmbeddingResponse)
async def create_embeddings(payload: EmbeddingRequest, current_user = Depends(get_current_user)):
    if not settings.hippo_embedding_url or not settings.hippo_embedding_key:
        raise HTTPException(status_code=503, detail='Embedding service not configured')
    headers = {"Authorization": f"Bearer {settings.hippo_embedding_key}", "Content-Type": "application/json"}
    body = {"texts": payload.texts}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(settings.hippo_embedding_url.rstrip('/') + '/embeddings', json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
            # expect {'embeddings': [[..], ...]}
            if isinstance(data, dict) and 'embeddings' in data:
                return {'embeddings': data['embeddings']}
            # fallback: if data is list
            if isinstance(data, list):
                return {'embeddings': data}
            raise HTTPException(status_code=502, detail='Unexpected embedding service response')
    except Exception as e:
        raise HTTPException(status_code=502, detail=f'Embedding service error: {e}')
