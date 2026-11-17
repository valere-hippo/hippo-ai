from __future__ import annotations

from typing import Any

from app.services.chat_payloads import build_message_content


DEFAULT_BATCH_MAX_ITEMS = 6
DEFAULT_BATCH_MAX_CHARS = 18000


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


def build_segmented_attachment_analysis_context(
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

    question_text = (question or "").strip()
    batch_total = len(batches)
    segments: list[str] = []

    for index, batch in enumerate(batches, start=1):
        file_blocks: list[str] = []
        for attachment in batch:
            attachment_context = build_message_content(question_text, [attachment], include_images=True)
            if isinstance(attachment_context, list):
                attachment_context = "\n".join(
                    str(part.get("text") or "") if isinstance(part, dict) else str(part)
                    for part in attachment_context
                )
            attachment_context = str(attachment_context or "").strip()
            if not attachment_context:
                continue
            file_blocks.append(attachment_context)
        if not file_blocks:
            continue
        header = [f"[Segment {index}/{batch_total}]"]
        if question_text:
            header.append(f"Fragestellung: {question_text}")
        names = [
            _attachment_fingerprint(attachment)
            for attachment in batch
            if _attachment_fingerprint(attachment)
        ]
        if names:
            header.append("Dateien: " + ", ".join(names))
        header.append("Inhalt:")
        segments.append("\n".join(header + file_blocks))

    return "\n\n".join(segments).strip()
