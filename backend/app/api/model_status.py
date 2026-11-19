from __future__ import annotations

from typing import Any

import asyncio
import httpx
from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.services.provider_clients import build_provider_headers, resolve_provider_runtime

router = APIRouter(prefix="/models", tags=["model-status"])

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "claude": "Claude",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "tencent": "Tencent",
}


def _extract_model_ids(payload: Any) -> list[str]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or payload.get("items") or []
    else:
        items = []
    model_ids: list[str] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("model") or item.get("name") or item.get("slug") or "").strip()
            if model_id and model_id not in model_ids:
                model_ids.append(model_id)
    return model_ids


async def _probe_provider(client: httpx.AsyncClient, provider: str) -> dict[str, Any]:
    runtime = resolve_provider_runtime(provider)
    label = PROVIDER_LABELS.get(runtime.tag, runtime.tag.title())
    configured = bool(runtime.api_url and runtime.api_key and runtime.model_name)
    result: dict[str, Any] = {
        "provider": runtime.tag,
        "label": label,
        "configured": configured,
        "api_url": runtime.api_url,
        "model": runtime.model_name,
        "status": "not_configured" if not configured else "checking",
        "available_models": [],
        "available": False,
        "error_message": None,
    }
    if not configured:
        return result

    headers = build_provider_headers(runtime.api_key)
    last_error: str | None = None
    for path in ("/v1/models", "/models"):
        try:
            response = await client.get(f"{runtime.api_url}{path}", headers=headers)
            response.raise_for_status()
            available_models = _extract_model_ids(response.json())
            result["available_models"] = available_models
            result["available"] = bool(available_models)
            result["status"] = "ok" if available_models else "empty"
            if runtime.model_name:
                result["configured_model_available"] = runtime.model_name in available_models
            return result
        except Exception as exc:
            last_error = str(exc)

    result["status"] = "error"
    result["error_message"] = last_error or "Unable to query provider models"
    return result


@router.get("/availability")
async def provider_model_availability(_current_user=Depends(get_current_user)):
    providers = ["openai", "claude", "deepseek", "qwen", "tencent"]
    async with httpx.AsyncClient(timeout=12.0) as client:
        results = await asyncio.gather(*(_probe_provider(client, provider) for provider in providers))
    return {"providers": results}
