from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.dependencies import get_current_user, DbSession
from app.core.config import settings
from sqlalchemy import text
import httpx

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


@router.post('/', response_model=SearchResponse)
async def semantic_search(payload: SearchRequest, db: DbSession, user = Depends(get_current_user)):
    # compute embedding for the query using hippo embedding endpoint if configured
    if not settings.hippo_embedding_url:
        raise HTTPException(status_code=503, detail='Embedding service URL not configured')

    # call hippo embedding endpoint (no key expected)
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(settings.hippo_embedding_url.rstrip('/') + '/embeddings', json={'texts':[payload.query]})
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and 'embeddings' in data:
                emb = data['embeddings'][0]
            elif isinstance(data, list):
                emb = data[0]
            else:
                raise Exception('Unexpected embedding response')
        except Exception as e:
            raise HTTPException(status_code=502, detail=f'Embedding error: {e}')

    # Query Postgres pgvector table — assumes table `ai_embeddings` with columns id, project_id, text, embedding (vector), metadata (jsonb)
    # Use <vector> <-> cube operator (pgvector uses <-> for distance)
    # Use 1 - distance as similarity score and cast param to vector
    sql = text(
        "SELECT id, text, metadata, 1 - (embedding <=> (:vec)::vector) AS similarity "
        f"FROM {EMBEDDINGS_TABLE} "
        + ("WHERE project_id = :project_id " if payload.project_id is not None else "")
        + "ORDER BY embedding <=> (:vec)::vector LIMIT :k OFFSET :offset"
    )

    params = {'vec': emb, 'k': payload.top_k, 'offset': payload.offset}
    if payload.project_id is not None:
        params['project_id'] = payload.project_id

    try:
        res = await db.execute(sql, params)
        rows = res.fetchall()
        results = []
        for r in rows:
            results.append({'id': r[0], 'text': r[1], 'score': float(r[3]), 'metadata': r[2]})
        next_offset = payload.offset + payload.top_k if len(rows) == payload.top_k else None
        return {'results': results, 'next_offset': next_offset}
    except Exception as e:
        # detect common pgvector / missing-table issues and return a helpful message
        err_msg = str(e)
        if 'UndefinedTableError' in err_msg or 'relation "ai_embeddings" does not exist' in err_msg or 'relation "embeddings" does not exist' in err_msg:
            raise HTTPException(status_code=503, detail=f'Embeddings table not found in schema "{settings.postgres_schema}" or pgvector not installed. Run migrations and install the pgvector extension.')
        raise HTTPException(status_code=500, detail=f'Database error: {e}')
