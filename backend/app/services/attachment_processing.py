from __future__ import annotations

import base64
import binascii
import re
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

MAX_ATTACHMENT_TEXT_CHARS = 12000
MAX_PDF_PAGES = 12


def _attachment_name(attachment: Any) -> str:
    return (getattr(attachment, "filename", None) or "attachment").strip() or "attachment"


def _attachment_mime_type(attachment: Any) -> str:
    return (getattr(attachment, "mime_type", None) or "").strip().lower()


def _attachment_base64(attachment: Any) -> str:
    raw_base64 = (getattr(attachment, "raw_base64", None) or "").strip()
    if raw_base64:
        return raw_base64
    data_url = (getattr(attachment, "data_url", None) or "").strip()
    if data_url.startswith("data:") and "," in data_url:
        return data_url.split(",", 1)[1]
    return ""


def _decode_attachment_bytes(attachment: Any) -> bytes:
    payload = _attachment_base64(attachment)
    if not payload:
        return b""
    try:
        return base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return b""


def _truncate(text: str, limit: int = MAX_ATTACHMENT_TEXT_CHARS) -> str:
    text = re.sub(r"\s+\n", "\n", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""

    try:
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                parts.append(page_text.strip())
        return _truncate("\n\n".join(parts))
    except Exception:
        return ""


def _extract_text_from_docx(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError):
        return ""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text_parts = [node.text for node in paragraph.findall(".//w:t", namespace) if node.text]
        line = "".join(text_parts).strip()
        if line:
            paragraphs.append(line)
    return _truncate("\n\n".join(paragraphs))


def _extract_text_from_plain_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return _truncate(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return ""


def _image_metadata(data: bytes) -> str:
    try:
        from PIL import Image  # type: ignore
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            mode = image.mode or "unknown"
            fmt = (image.format or "").upper() or "image"
            return f"{fmt} image {width}x{height} ({mode})"
    except Exception:
        return "image attachment"


def extract_attachment_text(attachment: Any) -> str:
    existing_text = (getattr(attachment, "ocr_text", None) or "").strip()
    if existing_text:
        return _truncate(existing_text)

    mime_type = _attachment_mime_type(attachment)
    filename = _attachment_name(attachment)
    data = _decode_attachment_bytes(attachment)
    if not data:
        return ""

    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return _extract_text_from_pdf(data)

    if (
        mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or filename.lower().endswith(".docx")
    ):
        return _extract_text_from_docx(data)

    if mime_type.startswith("text/") or filename.lower().endswith((".txt", ".md", ".csv", ".log", ".rtf")):
        return _extract_text_from_plain_text(data)

    return ""


def attachment_context_text(attachment: Any) -> str:
    filename = _attachment_name(attachment)
    mime_type = _attachment_mime_type(attachment) or "unknown"
    extracted_text = extract_attachment_text(attachment)
    lines = [f"[Attachment: {filename} | {mime_type}]"]
    if extracted_text:
        lines.append("[Content]")
        lines.append(extracted_text)
    elif mime_type.startswith("image/") or filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        lines.append(f"[Image metadata] {_image_metadata(_decode_attachment_bytes(attachment))}")
    return "\n".join(lines)
