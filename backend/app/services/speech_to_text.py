from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings

try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    WhisperModel = None


@lru_cache(maxsize=1)
def _load_model() -> Any:
    if WhisperModel is None:
        raise RuntimeError("faster-whisper is not installed.")

    return WhisperModel(
        settings.stt_model,
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
    )


def transcribe_audio_file(audio_path: str | Path) -> str:
    model = _load_model()
    language = (settings.stt_language or "").strip() or None

    segments, _info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
    )

    parts: list[str] = []
    for segment in segments:
        text = getattr(segment, "text", "") or ""
        text = text.strip()
        if text:
            parts.append(text)

    return " ".join(parts).strip()
