from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def _normalize_vision_base_url(value: str | None) -> str | None:
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


def _build_vision_prompt(user_message: str | None, filename: str | None = None) -> str:
    parts = [
        "Analyse l'image de manière précise et factuelle.",
        "Décris ce qui est visible, l'organisation de la scène, les objets, les couleurs, les textes lisibles, les symboles et la mise en page.",
        "Si l'image est une carte, un plan, un schéma, une capture d'écran, un graphique ou un document scanné, décris la structure et extrais les informations utiles.",
        "N'invente pas des détails qui ne sont pas visibles.",
        "Réponds dans la langue de la demande utilisateur et privilégie des phrases claires ou des puces courtes.",
    ]
    if user_message:
        parts.insert(0, f"Question ou contexte utilisateur: {user_message.strip()}")
    if filename:
        parts.append(f"Nom de fichier: {filename}")
    return "\n".join(parts)


def _build_vision_messages(user_message: str | None, attachment: Any) -> list[dict[str, Any]]:
    data_url = _attachment_data_url(attachment)
    if not data_url:
        return []
    prompt = _build_vision_prompt(user_message, _attachment_name(attachment))
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url,
                        "detail": "high",
                    },
                },
            ],
        }
    ]


async def _call_vision_model(user_message: str | None, attachment: Any) -> str:
    vision_url = _normalize_vision_base_url(settings.hippo_vision_url or settings.hippo_api_url)
    api_key = (settings.hippo_api_key or "").strip()
    if not vision_url or not api_key or not attachment_is_image(attachment):
        return ""

    messages = _build_vision_messages(user_message, attachment)
    if not messages:
        return ""

    payload = {
        "model": settings.hippo_model,
        "messages": messages,
        "max_tokens": 700,
        "temperature": 0.1,
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                vision_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("choices"):
                content = data["choices"][0]["message"]["content"]
            else:
                content = str(data)
            return str(content).strip()
    except Exception as exc:
        logger.warning("Vision analysis failed for %s: %s", _attachment_name(attachment), exc)
        return ""


async def summarize_image_attachment(user_message: str | None, attachment: Any) -> str:
    summary = await _call_vision_model(user_message, attachment)
    if not summary:
        return ""

    filename = _attachment_name(attachment)
    mime_type = _attachment_mime_type(attachment) or "image/*"
    return f"[Attachment: {filename} | {mime_type}]\n[Vision analysis]\n{summary}"


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
            from app.services.attachment_processing import attachment_context_text

            lines.append(attachment_context_text(attachment))

    if image_tasks:
        for _, attachment, task in image_tasks:
            summary = await task
            if summary:
                lines.append(summary)
            else:
                from app.services.attachment_processing import attachment_context_text

                lines.append(attachment_context_text(attachment))

    return "\n".join(line for line in lines if line).strip()


async def summarize_project_image_file(project: Any, filename: str, content_type: str | None = None) -> str:
    from app.services.project_storage import read_project_file

    try:
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
    return await summarize_image_attachment(None, temp_attachment)
