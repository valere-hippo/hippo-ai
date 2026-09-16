from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from typing import Any

from app.services.attachment_processing import attachment_context_text

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def _attachment_name(attachment: Any) -> str:
    return (getattr(attachment, "filename", None) or "attachment").strip() or "attachment"


def _attachment_mime_type(attachment: Any) -> str:
    mime_type = (getattr(attachment, "mime_type", None) or "").strip().lower()
    if mime_type:
        return mime_type
    filename = _attachment_name(attachment).lower()
    guessed = mimetypes.guess_type(filename)[0] or ""
    return guessed.lower()


def _attachment_data_url(attachment: Any) -> str:
    data_url = (getattr(attachment, "data_url", None) or "").strip()
    if data_url:
        return data_url
    raw_base64 = (getattr(attachment, "raw_base64", None) or "").strip()
    mime_type = _attachment_mime_type(attachment) or "image/png"
    if raw_base64:
        return f"data:{mime_type};base64,{raw_base64}"
    return ""


def attachment_is_image(attachment: Any) -> bool:
    mime_type = _attachment_mime_type(attachment)
    filename = _attachment_name(attachment).lower()
    data_url = _attachment_data_url(attachment).lower()
    return mime_type.startswith("image/") or filename.endswith(tuple(IMAGE_EXTENSIONS)) or data_url.startswith("data:image/")


async def summarize_image_attachment(user_message: str | None, attachment: Any) -> str:
    # Local-only fallback: use OCR / metadata extraction and avoid external vision calls.
    def _temp_attachment() -> Any:
        return type(
            "VisionAttachment",
            (),
            {
                "filename": _attachment_name(attachment),
                "mime_type": _attachment_mime_type(attachment),
                "data_url": _attachment_data_url(attachment),
                "raw_base64": getattr(attachment, "raw_base64", None),
                "ocr_text": getattr(attachment, "ocr_text", None),
            },
        )()

    summary = attachment_context_text(_temp_attachment())
    if user_message and user_message.strip() and summary:
        return f"{summary}\n[Context] {user_message.strip()}"
    return summary


async def build_vision_enriched_text(message: str, attachments: list[Any] | None = None) -> str:
    attachments = attachments or []
    lines: list[str] = []
    if message and message.strip():
        lines.append(message.strip())

    image_tasks: list[tuple[int, Any, asyncio.Task[str]]] = []
    for index, attachment in enumerate(attachments):
        if attachment_is_image(attachment):
            image_tasks.append((index, attachment, asyncio.create_task(summarize_image_attachment(message, attachment))))
        else:
            lines.append(attachment_context_text(attachment))

    if image_tasks:
        for _, attachment, task in image_tasks:
            try:
                summary = await task
            except Exception:
                summary = ""
            if summary:
                lines.append(summary)
            else:
                lines.append(attachment_context_text(attachment))

    return "\n".join(line for line in lines if line).strip()


async def summarize_project_image_file(project: Any, filename: str, content_type: str | None = None) -> str:
    from app.services.project_storage import read_project_file

    try:
        if getattr(project, "pcloud_path", None):
            data, mime_type, _storage = await asyncio.to_thread(read_project_file, project, filename)
        else:
            data, mime_type, _storage = read_project_file(project, filename)
    except Exception:
        return ""

    guessed_mime = (content_type or mime_type or mimetypes.guess_type(filename)[0] or "image/*").lower()
    if not guessed_mime.startswith("image/"):
        return ""

    data_url = f"data:{guessed_mime};base64,{base64.b64encode(data).decode('ascii')}"
    temp_attachment = type(
        "VisionAttachment",
        (),
        {
            "filename": filename,
            "mime_type": guessed_mime,
            "data_url": data_url,
            "raw_base64": None,
            "ocr_text": None,
        },
    )()
    return attachment_context_text(temp_attachment)
