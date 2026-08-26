from __future__ import annotations

from typing import Any


def _attachment_text(attachment: Any) -> str:
    filename = getattr(attachment, "filename", "attachment")
    mime_type = getattr(attachment, "mime_type", None) or "unknown"
    ocr_text = (getattr(attachment, "ocr_text", None) or "").strip()
    if ocr_text:
        return f"[Attachment: {filename} | {mime_type}]\n[OCR]\n{ocr_text}"
    return f"[Attachment: {filename} | {mime_type}]"


def build_message_content(
    message: str,
    attachments: list[Any] | None = None,
    include_images: bool = True,
) -> list[dict[str, Any]] | str:
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
        ocr_text = (getattr(attachment, "ocr_text", None) or "").strip()
        if ocr_text:
            text_parts.append(f"[OCR from {filename}]\n{ocr_text}")
        if include_images and data_url and mime_type.startswith("image/"):
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url,
                        "detail": "auto",
                    },
                }
            )
        else:
            text_parts.append(_attachment_text(attachment))

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
        lines.append(_attachment_text(attachment))
    return "\n".join(lines).strip()


def derive_conversation_title(message: str, attachments: list[Any] | None = None, max_length: int = 64) -> str:
    attachments = attachments or []
    base_text = (message or "").strip().replace("\n", " ")
    if not base_text:
        for attachment in attachments:
            filename = getattr(attachment, "filename", None)
            if filename:
                base_text = filename.strip()
                break
    if not base_text:
        return "Neuer Chat"
    if len(base_text) > max_length:
        return base_text[: max_length - 1].rstrip() + "…"
    return base_text
