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


async def search_embedding_context(db: Any, query: str, project_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query or not settings.hippo_embedding_url:
        return []

    embedding = await _get_query_embedding(query)
    if not embedding:
        return []

    sql = text(
        "SELECT id, text, metadata, 1 - (embedding <=> (:vec)::vector) AS similarity "
        f"FROM {EMBEDDINGS_TABLE} "
        + ("WHERE project_id = :project_id " if project_id is not None else "")
        + "ORDER BY embedding <=> (:vec)::vector LIMIT :k"
    )

    params: dict[str, Any] = {"vec": embedding, "k": limit}
    if project_id is not None:
        params["project_id"] = project_id

    result = await db.execute(sql, params)
    rows = result.fetchall()
    return [
        {
            "id": row[0],
            "text": row[1],
            "score": float(row[3]),
            "metadata": row[2],
        }
        for row in rows
    ]


def format_embedding_context(items: list[dict[str, Any]], title: str = "Gefundene Projekthinweise aus dem Embedding-Store") -> str:
    if not items:
        return ""
    lines = [title + ":"]
    for item in items:
        text_value = str(item.get("text") or "").strip()
        if text_value:
            lines.append(f"- {text_value}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


async def build_embedding_context_for_request(db: Any, query: str, project_id: int | None = None, limit: int = 5) -> str:
    scoped_items = await search_embedding_context(db, query, project_id=project_id, limit=limit) if project_id is not None else []
    global_items = await search_embedding_context(db, query, project_id=None, limit=limit)

    if project_id is not None:
        if scoped_items:
            scoped_ids = {item.get("id") for item in scoped_items}
            global_items = [item for item in global_items if item.get("id") not in scoped_ids]
        sections: list[str] = []
        scoped_block = format_embedding_context(scoped_items, "Projektspezifische Hinweise aus dem Embedding-Store")
        if scoped_block:
            sections.append(scoped_block)
        global_block = format_embedding_context(global_items, "Zusätzliche Hinweise aus anderen Projekten")
        if global_block:
            sections.append(global_block)
        return "\n\n".join(sections).strip()

    return format_embedding_context(global_items, "Gefundene Projekthinweise aus dem Embedding-Store")
