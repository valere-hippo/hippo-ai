from __future__ import annotations

from typing import Any

from app.services.attachment_processing import attachment_context_text


def build_attachment_response_guidance() -> str:
    return (
        "Wenn die Antwort auf einem angehängten Dokument, Bild oder Screenshot basiert, antworte ausführlicher als üblich.\n"
        "Erkläre zuerst kurz, worum es sich bei der Datei handelt, dann die wichtigsten Inhalte oder erkannten Elemente, "
        "danach die relevantesten Details oder Auffälligkeiten und schließe mit einer kompakten Einordnung.\n"
        "Wenn der Benutzer eine Analyse des gemeinsamen Ordners, einer Datei oder mehrerer Dateien möchte, liefere eine strukturierte Antwort mit Überblick, Dateiliste, Details und Fazit.\n"
        "Verwende bei solchen Anfragen lieber mehrere Absätze, nummerierte Schritte, Aufzählungspunkte und klare Zwischenüberschriften als nur ein bis zwei kurze Sätze.\n"
        "Schreibe Überschriften sauber und ohne dekorative Markdown-Rahmen wie ###** oder **###.\n"
        "Vermeide rohe Markdown-Tabellen, wenn eine normale Liste oder ein kurzer erklärender Satz besser lesbar ist.\n"
        "Formuliere die Antwort so, dass sie sich in einzelne Abschnitte gliedert wie in einem professionell gesetzten Dokument.\n"
        "Bei deutschen Anfragen antworte auf Deutsch und verwende eine klare, strukturierte Sprache.\n"
        "Gib keine internen Gedanken aus und erwähne keine <think>-Blöcke."
    )


def attachment_has_image(attachment: Any) -> bool:
    mime_type = (getattr(attachment, "mime_type", None) or "").lower()
    data_url = (getattr(attachment, "data_url", None) or "").lower()
    return mime_type.startswith("image/") or data_url.startswith("data:image/")


def attachments_contain_images(attachments: list[Any] | None = None) -> bool:
    return any(attachment_has_image(attachment) for attachment in (attachments or []))


def _attachment_text(attachment: Any) -> str:
    return attachment_context_text(attachment)


def build_message_content(
    message: str,
    attachments: list[Any] | None = None,
    include_images: bool = True,
) -> list[dict[str, Any]] | str:
    attachments = attachments or []
    image_parts: list[dict[str, Any]] = []
    text_parts: list[str] = []
    has_images = include_images and attachments_contain_images(attachments)

    base_text = message.strip() if message else ""
    if base_text:
        text_parts.append(base_text)

    for attachment in attachments:
        filename = getattr(attachment, "filename", "attachment")
        mime_type = (getattr(attachment, "mime_type", None) or "").lower()
        data_url = getattr(attachment, "data_url", None)
        if has_images and data_url and mime_type.startswith("image/"):
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
