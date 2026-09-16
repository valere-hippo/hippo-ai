from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings


def _normalize_chat_base_url(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    if raw.endswith("/v1/chat/completions"):
        return raw
    if raw.endswith("/v1"):
        return f"{raw}/chat/completions"
    return f"{raw}/v1/chat/completions"


@lru_cache(maxsize=16)
def _guess_mime_type(audio_path: str | Path) -> str:
    suffix = Path(audio_path).suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
    }.get(suffix, "audio/webm")


def _audio_to_data_url(audio_path: str | Path) -> str:
    data = Path(audio_path).read_bytes()
    mime_type = _guess_mime_type(audio_path)
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


async def transcribe_audio_file(audio_path: str | Path) -> str:
    model_url = _normalize_chat_base_url(settings.hippo_api_url)
    if not model_url:
        raise RuntimeError("HIPPO_AI_BASE_URL is not configured.")

    data_url = _audio_to_data_url(audio_path)
    prompt = (
        "Transkribiere dieses Audio wörtlich und ohne zusätzliche Kommentare. "
        "Wenn die Sprache erkennbar ist, behalte sie bei. "
        "Gib nur den reinen Text zurück."
    )
    payload: dict[str, Any] = {
        "model": settings.hippo_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "audio_url", "audio_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": 1024,
    }
    headers = {"Content-Type": "application/json"}
    api_key = (settings.hippo_api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        response = await client.post(model_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    if isinstance(data, dict) and data.get("choices"):
        content = data["choices"][0]["message"].get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                    if text:
                        parts.append(str(text))
                elif part:
                    parts.append(str(part))
            return " ".join(parts).strip()
        return str(content or "").strip()

    return str(data).strip()
