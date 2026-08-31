from __future__ import annotations

from typing import Any

from app.services.attachment_processing import attachment_context_text
import re


def build_attachment_response_guidance() -> str:
    return (
        "Wenn die Antwort auf einem angehängten Dokument, Bild oder Screenshot basiert, antworte ausführlicher als üblich.\n"
        "Erkläre zuerst kurz, worum es sich bei der Datei handelt, dann die wichtigsten Inhalte oder erkannten Elemente, "
        "danach die relevantesten Details oder Auffälligkeiten und schließe mit einer kompakten Einordnung.\n"
        "Wenn der Benutzer eine Analyse des gemeinsamen Ordners, einer Datei oder mehrerer Dateien möchte, liefere eine strukturierte Antwort mit Überblick, Dateiliste, Details und Fazit.\n"
        "Verwende bei solchen Anfragen lieber mehrere Absätze, nummerierte Schritte, Aufzählungspunkte und klare Zwischenüberschriften als nur ein bis zwei kurze Sätze.\n"
        "Wenn der Benutzer eine ausführliche Antwort erwartet, entwickle die Antwort vollständig aus und vermeide unnötige Kürze.\n"
        "Bevorzuge eine tiefere Erklärung mit Beispielen, Einordnung und sauberen Übergängen statt einer knappen Stichwortliste.\n"
        "Schreibe Überschriften sauber und ohne dekorative Markdown-Rahmen wie ###** oder **###.\n"
        "Vermeide rohe Markdown-Tabellen, wenn eine normale Liste oder ein kurzer erklärender Satz besser lesbar ist.\n"
        "Formuliere die Antwort so, dass sie sich in einzelne Abschnitte gliedert wie in einem professionell gesetzten Dokument.\n"
        "Bei deutschen Anfragen antworte auf Deutsch und verwende eine klare, strukturierte Sprache.\n"
        "Antworte standardmäßig als Text im Chat. Erzeuge nur dann eine Datei, wenn der Benutzer ausdrücklich ein Word-, PDF-, Bild- oder anderes Dateiformat verlangt.\n"
        "Wenn der Benutzer ein Bild nur beschreiben, analysieren oder zusammenfassen möchte, antworte in Text und liefere keine Bilddatei.\n"
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


IMAGE_GEN_VERB_RE = re.compile(r"\b(erstelle|erzeuge|generiere|male|zeichne|render|mach|create|generate|draw|make|produce|fais|cr[eé]e|fabrique)\b", re.IGNORECASE)
IMAGE_GEN_NOUN_RE = re.compile(r"\b(png|jpg|jpeg|image|bild|photo|foto|poster|illustration|grafik|diagramm|karte|map|svg|logo|icon)\b", re.IGNORECASE)
GEODATA_VISUAL_NOUN_RE = re.compile(r"\b(karte|map|polygon|polygone|territorium|territorial|revier|gebiet|geodaten|koordinaten|coordinate|coordinates|diagramm|plot|gis)\b", re.IGNORECASE)
IMAGE_ANALYSIS_RE = re.compile(
    r"\b(describe|beschreibe|erkl[aä]re|analyse|analysiere|sag\s+mir|was\s+siehst\s+du|what\s+do\s+you\s+see|que\s+vois[- ]tu|dis[- ]moi)\b",
    re.IGNORECASE,
)


def looks_like_image_generation_request(message: str, attachments: list[Any] | None = None) -> bool:
    text = " ".join(
        part
        for part in [
            (message or "").strip(),
            " ".join(getattr(att, "filename", "") for att in (attachments or []) if getattr(att, "filename", "")),
        ]
        if part
    ).strip()
    if not text:
        return False
    if "16:9" in text or "16x9" in text:
        return True
    has_explicit_output_hint = bool(re.search(r"\b(als\s+bild|als\s+datei|im\s+format|dateiblock|file\s+block|exportiere|export|speichere)\b", text, re.IGNORECASE))
    return bool(IMAGE_GEN_VERB_RE.search(text) and (IMAGE_GEN_NOUN_RE.search(text) or has_explicit_output_hint))


def looks_like_geodata_visual_request(message: str, attachments: list[Any] | None = None) -> bool:
    text = " ".join(
        part
        for part in [
            (message or "").strip(),
            " ".join(getattr(att, "filename", "") for att in (attachments or []) if getattr(att, "filename", "")),
        ]
        if part
    ).strip()
    if not text:
        return False
    return bool(IMAGE_GEN_VERB_RE.search(text) and GEODATA_VISUAL_NOUN_RE.search(text))


def looks_like_image_analysis_request(message: str, attachments: list[Any] | None = None) -> bool:
    text = " ".join(
        part
        for part in [
            (message or "").strip(),
            " ".join(getattr(att, "filename", "") for att in (attachments or []) if getattr(att, "filename", "")),
        ]
        if part
    ).strip()
    if not text:
        return False
    return bool(IMAGE_ANALYSIS_RE.search(text))
