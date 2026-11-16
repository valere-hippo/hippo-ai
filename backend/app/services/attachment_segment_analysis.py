from __future__ import annotations

from typing import Any

import httpx

from app.services.chat_payloads import build_message_content
from app.services.provider_clients import build_chat_completion_payload, build_provider_headers


DEFAULT_BATCH_MAX_ITEMS = 6
DEFAULT_BATCH_MAX_CHARS = 18000
DEFAULT_SEGMENT_MAX_TOKENS = 1400


def _attachment_fingerprint(attachment: Any) -> str:
    filename = (getattr(attachment, "filename", None) or "").strip()
    mime_type = (getattr(attachment, "mime_type", None) or "").strip()
    file_path = (getattr(attachment, "file_path", None) or "").strip()
    return " | ".join(part for part in (filename, mime_type, file_path) if part)


def _attachment_weight(attachment: Any) -> int:
    content = build_message_content("", [attachment], include_images=True)
    if isinstance(content, str):
        return len(content)
    text_parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text_parts.append(str(part.get("text") or ""))
        elif part.get("type") == "image_url":
            image_url = part.get("image_url") or {}
            url = str(image_url.get("url") or "")
            text_parts.append(f"[IMAGE:{url[:80]}]")
    return len("\n".join(text_parts))


def split_attachments_for_analysis(
    attachments: list[Any] | None,
    *,
    max_items: int = DEFAULT_BATCH_MAX_ITEMS,
    max_chars: int = DEFAULT_BATCH_MAX_CHARS,
) -> list[list[Any]]:
    items = [attachment for attachment in (attachments or []) if attachment is not None]
    if not items:
        return []

    batches: list[list[Any]] = []
    current: list[Any] = []
    current_chars = 0

    for attachment in items:
        weight = max(1, _attachment_weight(attachment))
        if current and (len(current) >= max_items or current_chars + weight > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(attachment)
        current_chars += weight

    if current:
        batches.append(current)
    return batches


async def build_segmented_attachment_analysis_context(
    attachments: list[Any] | None,
    *,
    question: str,
    chat_api_url: str,
    api_key: str | None,
    model_name: str | None,
    request_timeout_seconds: int = 180,
) -> str:
    batches = split_attachments_for_analysis(attachments)
    if not batches:
        return ""

    headers = build_provider_headers(api_key)
    segments: list[str] = []
    batch_total = len(batches)

    async with httpx.AsyncClient(timeout=httpx.Timeout(request_timeout_seconds, connect=15.0)) as client:
        for index, batch in enumerate(batches, start=1):
            batch_context = build_message_content(question, batch, include_images=True)
            system_prompt = (
                "Du liest genau einen Dateisegment-Block aus einem Projekt. "
                "Lies jede Datei in diesem Segment vollständig, nenne konkrete Fakten, und vermeide generische Einleitungen. "
                "Wenn mehrere Dateien enthalten sind, behandle sie getrennt mit Dateiname und Inhalt. "
                "Wenn du etwas nicht lesen kannst, sage es explizit. "
                "Antworte auf Deutsch und liefere nur inhaltliche Beobachtungen ohne Meta-Kommentare."
            )
            user_prompt = (
                f"Segment {index}/{batch_total}\n"
                "Analysiere diesen Dateisegment-Block und fasse ihn präzise zusammen. "
                "Die Antwort wird später mit anderen Segmenten zusammengeführt, also fokussiere auf Fakten, Inhalte und auffällige Details."
            )
            payload = build_chat_completion_payload(
                model_name,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [{"type": "text", "text": user_prompt}] if isinstance(batch_context, str) and not batch_context else batch_context},
                ],
                max_tokens=DEFAULT_SEGMENT_MAX_TOKENS,
                temperature=0.1,
            )
            response = await client.post(chat_api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("choices"):
                content = data["choices"][0]["message"]["content"]
            else:
                content = str(data)
            if isinstance(content, str):
                text = content.strip()
            else:
                text = str(content).strip()
            if text:
                file_names = [
                    _attachment_fingerprint(attachment)
                    for attachment in batch
                    if _attachment_fingerprint(attachment)
                ]
                header = f"[Segment {index}/{batch_total}]"
                if file_names:
                    header += " " + ", ".join(file_names)
                segments.append(f"{header}\n{text}")

    return "\n\n".join(segments).strip()
