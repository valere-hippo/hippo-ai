from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.model_registry import ModelRegistry


@dataclass(slots=True)
class ModelRegistrySource:
    provider: str
    source_url: str | None
    api_key: str | None
    capability: str


MODEL_SYNC_SOURCES: tuple[ModelRegistrySource, ...] = (
    ModelRegistrySource(provider="chat", source_url=settings.hippo_api_url, api_key=settings.hippo_api_key, capability="chat"),
    ModelRegistrySource(provider="vision", source_url=settings.hippo_vision_url, api_key=settings.hippo_api_key, capability="vision"),
)


def _normalize_base_url(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/")


def _candidate_model_paths() -> tuple[str, ...]:
    return ("/v1/models", "/models")


def _extract_model_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(key in payload for key in ("id", "model", "name")):
            return [payload]
    return []


def _extract_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    continue
    return None


def _normalize_model_row(source: ModelRegistrySource, model: dict[str, Any], source_url: str) -> dict[str, Any]:
    model_id = str(model.get("id") or model.get("model") or model.get("name") or model.get("slug") or source.provider)
    display_name = model.get("display_name") or model.get("name") or model.get("owned_by") or model.get("ownedBy")
    context_window = _extract_int(
        model,
        (
            "context_window",
            "context_length",
            "context_length_tokens",
            "max_model_len",
            "max_input_tokens",
            "n_ctx",
        ),
    )
    max_output_tokens = _extract_int(
        model,
        (
            "max_output_tokens",
            "max_completion_tokens",
            "max_tokens",
            "output_tokens",
        ),
    )
    return {
        "provider": source.provider,
        "source_url": source_url,
        "capability": source.capability,
        "model_id": model_id,
        "display_name": str(display_name) if display_name is not None else None,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "status": "ok",
        "error_message": None,
        "raw_payload": model,
        "fetched_at": datetime.now(timezone.utc),
        "last_seen_at": datetime.now(timezone.utc),
    }


async def _upsert_model_registry(db: AsyncSession, row: dict[str, Any]) -> None:
    existing = await db.scalar(
        select(ModelRegistry).where(
            ModelRegistry.provider == row["provider"],
            ModelRegistry.source_url == row["source_url"],
            ModelRegistry.model_id == row["model_id"],
        )
    )
    if existing is None:
        db.add(ModelRegistry(**row))
        return

    for key, value in row.items():
        setattr(existing, key, value)


async def sync_model_registry(db: AsyncSession) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "sources": [],
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        for source in MODEL_SYNC_SOURCES:
            base_url = _normalize_base_url(source.source_url)
            if not base_url:
                summary["sources"].append({"provider": source.provider, "status": "skipped", "reason": "missing_url"})
                continue

            headers: dict[str, str] = {"Content-Type": "application/json"}
            if source.api_key:
                headers["Authorization"] = f"Bearer {source.api_key}"

            payload: Any = None
            last_error: str | None = None
            for path in _candidate_model_paths():
                try:
                    response = await client.get(f"{base_url}{path}", headers=headers)
                    response.raise_for_status()
                    payload = response.json()
                    break
                except Exception as exc:
                    last_error = str(exc)
                    payload = None

            entries = _extract_model_entries(payload)
            if not entries:
                summary["sources"].append(
                    {
                        "provider": source.provider,
                        "status": "error" if last_error else "empty",
                        "reason": last_error or "no_model_entries",
                    }
                )
                continue

            persisted = 0
            for entry in entries:
                await _upsert_model_registry(db, _normalize_model_row(source, entry, base_url))
                persisted += 1

            summary["sources"].append(
                {
                    "provider": source.provider,
                    "status": "ok",
                    "models": persisted,
                    "source_url": base_url,
                }
            )

    await db.commit()
    return summary


async def get_latest_model(db: AsyncSession, provider: str) -> ModelRegistry | None:
    result = await db.execute(
        select(ModelRegistry)
        .where(ModelRegistry.provider == provider)
        .order_by(ModelRegistry.last_seen_at.desc(), ModelRegistry.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def resolve_chat_model_name(db: AsyncSession, fallback: str) -> str:
    latest = await get_latest_model(db, "chat")
    if latest and latest.status == "ok" and latest.model_id:
        return latest.model_id
    return fallback


async def resolve_chat_max_tokens(db: AsyncSession, default_tokens: int, long_tokens: int) -> int:
    latest = await get_latest_model(db, "chat")
    max_tokens = long_tokens if long_tokens > default_tokens else default_tokens
    if latest and latest.status == "ok" and latest.max_output_tokens:
        max_tokens = min(max_tokens, latest.max_output_tokens)
    if latest and latest.status == "ok" and latest.context_window:
        max_tokens = min(max_tokens, max(latest.context_window - 1024, 512))
    return max_tokens
