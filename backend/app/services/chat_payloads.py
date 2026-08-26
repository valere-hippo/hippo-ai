from __future__ import annotations

from typing import Any


def build_message_content(message: str, attachments: list[Any] | None = None) -> list[dict[str, Any]] | str:
    attachments = attachments or []
    image_parts: list[dict[str, Any]] = []
    text_parts: list[str] = []

    base_text = message.strip() if message else ""
    if base_text:
        text_parts.append(base_text)

    for attachment in attachments:
        filename = getattr(attachment, "filename", "attachment")
        mime_type = (getattr(attachment, "mime_type", None) or "").lower()
        data_url = getattr(attachment, "data_url", None)
        if data_url and mime_type.startswith("image/"):
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                }
            )
        else:
            text_parts.append(f"[Attachment: {filename}]")

    if not text_parts and not image_parts:
        return ""

    content: list[dict[str, Any]] = []
    if text_parts:
        content.append({"type": "text", "text": "\n".join(text_parts)})
    content.extend(image_parts)
    return content if len(content) > 1 or image_parts else content[0]["text"]


def storage_text(message: str, attachments: list[Any] | None = None) -> str:
    attachments = attachments or []
    lines = [message.strip()] if message and message.strip() else []
    for attachment in attachments:
        filename = getattr(attachment, "filename", "attachment")
        mime_type = getattr(attachment, "mime_type", None) or "unknown"
        lines.append(f"[Attachment: {filename} | {mime_type}]")
    return "\n".join(lines).strip()
