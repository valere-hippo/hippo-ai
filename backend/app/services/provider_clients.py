from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass(slots=True)
class ProviderRuntime:
    tag: str
    api_url: str | None
    api_key: str | None
    model_name: str | None


PROVIDER_DEFAULT_MODELS = {
    "openai": settings.hippo_model,
    "claude": "claude-3-5-sonnet",
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
    "tencent": "hunyuan-turbo",
}


def _normalize_base_url(url: str | None) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return raw.rstrip("/")


PROVIDER_URL_FIELDS = {
    "openai": ("hippo_api_url", "hippo_api_key", "hippo_model"),
    "claude": ("claude_api_url", "claude_api_key", "claude_model"),
    "deepseek": ("deepseek_api_url", "deepseek_api_key", "deepseek_model"),
    "qwen": ("qwen_api_url", "qwen_api_key", "qwen_model"),
    "tencent": ("tencent_api_url", "tencent_api_key", "tencent_model"),
}


def resolve_provider_runtime(tag: str | None) -> ProviderRuntime:
    provider = (tag or "openai").strip().lower().lstrip("#") or "openai"
    if provider == "qween":
        provider = "qwen"
    if provider not in PROVIDER_URL_FIELDS:
        provider = "openai"
    url_field, key_field, model_field = PROVIDER_URL_FIELDS[provider]
    api_url = _normalize_base_url(getattr(settings, url_field, None))
    api_key = (getattr(settings, key_field, None) or "").strip() or None
    model_name = (getattr(settings, model_field, None) or "").strip() or PROVIDER_DEFAULT_MODELS.get(provider)
    return ProviderRuntime(tag=provider, api_url=api_url, api_key=api_key, model_name=model_name)


def build_provider_headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def model_uses_completion_tokens(model_name: str | None) -> bool:
    raw = (model_name or "").strip().lower()
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw.startswith("gpt-5") or raw.startswith("o1") or raw.startswith("o3") or raw.startswith("o4")


def build_chat_completion_payload(model_name: str | None, messages: list[dict[str, Any]], *, max_tokens: int, temperature: float = 0.2) -> dict[str, Any]:
    reasoning_model = model_uses_completion_tokens(model_name)
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "max_completion_tokens": max_tokens if reasoning_model else None,
        "temperature": None if reasoning_model else temperature,
    }
    if reasoning_model:
        payload.pop("temperature", None)
    else:
        payload["max_tokens"] = max_tokens
        payload.pop("max_completion_tokens", None)
        payload.pop("temperature", None)
    return payload
