from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import settings

EMBEDDINGS_TABLE = f"{settings.postgres_schema}.ai_embeddings"


async def _get_query_embedding(query: str) -> list[float] | None:
    if not settings.hippo_embedding_url:
        return None

    headers = {"Content-Type": "application/json"}
    if settings.hippo_embedding_key:
        headers["Authorization"] = f"Bearer {settings.hippo_embedding_key}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            settings.hippo_embedding_url.rstrip("/") + "/embeddings",
            json={"texts": [query]},
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
    return None


async def _search_remote_embedding_context(query: str, project_id: int, limit: int) -> list[dict[str, Any]]:
    if not settings.hippo_embedding_url:
        return []

    headers = {"Content-Type": "application/json"}
    if settings.hippo_embedding_key:
        headers["Authorization"] = f"Bearer {settings.hippo_embedding_key}"

    payload = {"project_id": project_id, "query": query, "limit": limit, "min_score": 0.0}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            settings.hippo_embedding_url.rstrip("/") + "/embeddings/search",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    items: list[dict[str, Any]] = []
    if isinstance(data, dict):
        raw_results = data.get("results")
        if isinstance(raw_results, list):
            items = raw_results
    elif isinstance(data, list):
        items = data

    normalized: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        text_value = str(row.get("text") or "").strip()
        if not text_value:
            continue
        normalized.append(
            {
                "id": row.get("id"),
                "text": text_value,
                "score": float(row.get("score") or row.get("similarity") or 0.0),
                "metadata": row.get("metadata"),
                "source": "remote",
            }
        )
    return normalized


async def _search_local_embedding_context(db: Any, query: str, project_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []

    embedding = await _get_query_embedding(query)
    if not embedding:
        return []

    sql = text(
        "SELECT id, text, metadata, 1 - (embedding <=> (:vec)::vector) AS similarity "
        f"FROM {EMBEDDINGS_TABLE} "
        + (
            "WHERE (project_id = :project_id OR project_id IS NULL) "
            if project_id is not None
            else "WHERE project_id IS NULL "
        )
        + "ORDER BY embedding <=> (:vec)::vector LIMIT :k"
    )

    params: dict[str, Any] = {"vec": embedding, "k": max(limit * 2, limit)}
    if project_id is not None:
        params["project_id"] = project_id

    try:
        result = await db.execute(sql, params)
        rows = result.fetchall()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
        return []

    return [
        {
            "id": row[0],
            "text": row[1],
            "score": float(row[3]),
            "metadata": row[2],
            "source": "local",
        }
        for row in rows
    ]


def _dedupe_embedding_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for item in items:
        text_value = str(item.get("text") or "").strip()
        if not text_value:
            continue
        key = str(item.get("id") or text_value).strip().lower()
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            order.append(key)
            continue
        if float(item.get("score") or 0.0) > float(existing.get("score") or 0.0):
            merged[key] = item
        if existing.get("source") == "remote" and item.get("source") == "local":
            merged[key] = item

    ranked = list(merged.values())
    ranked.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    return ranked[:limit]


async def search_embedding_context(db: Any, query: str, project_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
    if project_id is not None:
        local_items = await _search_local_embedding_context(db, query, project_id=project_id, limit=limit)
        remote_items: list[dict[str, Any]] = []
        try:
            remote_items = await _search_remote_embedding_context(query, project_id, limit)
        except Exception:
            remote_items = []
        merged = _dedupe_embedding_items(local_items + remote_items, limit=limit)
        if merged:
            return merged
        return local_items or remote_items

    return await _search_local_embedding_context(db, query, project_id=project_id, limit=limit)


def format_embedding_context(items: list[dict[str, Any]], title: str = "Gefundene Projekthinweise aus dem Embedding-Store") -> str:
    if not items:
        return ""
    lines = [title + ":", "Nutze diese Hinweise nur, wenn sie zur Anfrage passen. Bevorzuge die Hinweise mit höherer Relevanz."]
    for item in items[:5]:
        text_value = str(item.get("text") or "").strip()
        if not text_value:
            continue
        score = float(item.get("score") or 0.0)
        metadata = item.get("metadata")
        metadata_source = metadata.get("source") if isinstance(metadata, dict) else None
        source = str(item.get("source") or metadata_source or "store")
        lines.append(f"- [{score:.2f}] ({source}) {text_value}")
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


async def build_embedding_context_for_request(db: Any, query: str, project_id: int | None = None, limit: int = 5) -> str:
    scoped_items = await search_embedding_context(db, query, project_id=project_id, limit=limit)
    if not scoped_items:
        return ""

    title = "Projektspezifische Hinweise aus dem Embedding-Store" if project_id is not None else "Geteilte Hinweise aus dem Embedding-Store"
    return format_embedding_context(scoped_items, title)
