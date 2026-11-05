from __future__ import annotations

import base64
import binascii
import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
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


def _extract_text_from_image(data: bytes) -> str:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return ""

    try:
        import pytesseract  # type: ignore
    except Exception:
        return ""

    try:
        with Image.open(BytesIO(data)) as image:
            text = pytesseract.image_to_string(image, lang="deu+eng") or ""
            return _truncate(text)
    except Exception:
        return ""


GEO_ATTACHMENT_EXTENSIONS = (
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".gpkg",
    ".qgz",
    ".qgs",
    ".geojson",
    ".kml",
    ".kmz",
)

GEO_SHAPE_BUNDLE_EXTENSIONS = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def _attachment_filename_path(filename: str) -> Path:
    return Path((filename or "attachment").replace("\\", "/").split("/")[-1])


def _attachment_stem(filename: str) -> str:
    return _attachment_filename_path(filename).stem


def _attachment_related_geo_names(filename: str) -> list[str]:
    stem = _attachment_stem(filename)
    return [f"{stem}{ext}" for ext in GEO_SHAPE_BUNDLE_EXTENSIONS]


def _attachment_group_map(attachments: list[Any] | None = None) -> dict[str, Any]:
    grouped: dict[str, Any] = {}
    for attachment in attachments or []:
        name = _attachment_name(attachment).lower()
        grouped[name] = attachment
    return grouped


def _write_attachment_bytes(target: Path, attachment: Any) -> bool:
    data = _decode_attachment_bytes(attachment)
    if not data:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return True


def _extract_geo_bundle_context(attachments: list[Any], filename: str) -> str:
    related_names = _attachment_related_geo_names(filename)
    related_map = _attachment_group_map(attachments)
    related_attachments = [related_map.get(name.lower()) for name in related_names if related_map.get(name.lower())]
    if not any(att and _attachment_name(att).lower().endswith(".shp") for att in related_attachments):
        return ""

    stem = _attachment_stem(filename)
    parts = [f"Geodatenpaket für '{stem}':"]
    parts.append("- Enthaltene Dateien: " + ", ".join(_attachment_name(att) for att in related_attachments))

    try:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / stem
            for att in related_attachments:
                target = Path(tmpdir) / _attachment_name(att)
                _write_attachment_bytes(target, att)

            try:
                import shapefile  # type: ignore

                reader = shapefile.Reader(str(base))
                fields = [field for field in getattr(reader, "fields", [])[1:]]
                records = []
                try:
                    records = list(reader.records())
                except Exception:
                    records = []
                shape_type = getattr(reader, "shapeType", None)
                if shape_type is not None:
                    parts.append(f"- Geometrietyp: {shape_type}")
                bbox = getattr(reader, "bbox", None)
                if bbox:
                    parts.append(
                        "- Bounding Box: "
                        f"{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}"
                    )
                try:
                    shapes = list(reader.shapes())
                except Exception:
                    shapes = []
                parts.append(f"- Geometrien: {len(shapes)} Objekte")
                if fields:
                    formatted_fields = ", ".join(f"{field[0]} ({field[1]})" for field in fields[:10])
                    parts.append(f"- Felder: {formatted_fields}")
                record_count = getattr(reader, "numRecords", None)
                if record_count is None:
                    record_count = len(records)
                parts.append(f"- Datensätze: {record_count}")
                if records and fields:
                    first_record = records[0]
                    record_dict = first_record.as_dict() if hasattr(first_record, "as_dict") else {}
                    sample_parts = []
                    for field in fields[:8]:
                        field_name = field[0]
                        value = str(record_dict.get(field_name) or "").strip()
                        if value:
                            sample_parts.append(f"{field_name}={value}")
                    if sample_parts:
                        parts.append(f"- Beispielinhalt: {', '.join(sample_parts)}")
                return "\n".join(parts)
            except Exception:
                shp_path = Path(tmpdir) / f"{stem}.shp"
                if shp_path.exists():
                    parts.append("- Geometriedaten vorhanden, aber detaillierte Auswertung nicht möglich.")
                prj_path = Path(tmpdir) / f"{stem}.prj"
                if prj_path.exists():
                    prj_text = _extract_text_from_plain_text(prj_path.read_bytes())
                    if prj_text:
                        parts.append(f"- Projektion: {prj_text}")
                if (Path(tmpdir) / f"{stem}.dbf").exists():
                    parts.append("- DBF vorhanden: Attributtabelle für die Kontakte/Objekte.")
    except Exception:
        return ""

    return "\n".join(parts)


def extract_attachment_text(attachment: Any) -> str:
    existing_text = (getattr(attachment, "ocr_text", None) or "").strip()
    if existing_text:
        return _truncate(existing_text)

    mime_type = _attachment_mime_type(attachment)
    filename = _attachment_name(attachment)
    lower_name = filename.lower()
    data = _decode_attachment_bytes(attachment)
    if not data:
        if lower_name.endswith(GEO_ATTACHMENT_EXTENSIONS):
            return _truncate(
                f"[Geodaten-Datei: {filename}] Diese Datei gehört zu einem GIS/QGIS-Datensatz. "
                "Für eine echte inhaltliche Analyse müssen die Begleitdateien bzw. der Projektkontext mitausgewertet werden."
            )
        return ""

    if mime_type == "application/pdf" or lower_name.endswith(".pdf"):
        return _extract_text_from_pdf(data)

    if (
        mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or lower_name.endswith(".docx")
    ):
        return _extract_text_from_docx(data)

    if mime_type.startswith("image/") or lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")):
        return _extract_text_from_image(data)

    if mime_type.startswith("text/") or lower_name.endswith((".txt", ".md", ".csv", ".log", ".rtf")):
        return _extract_text_from_plain_text(data)

    if lower_name.endswith(GEO_ATTACHMENT_EXTENSIONS):
        return _truncate(
            f"[Geodaten-Datei: {filename}] Diese Datei gehört zu einem GIS/QGIS-Datensatz. "
            "Für eine echte inhaltliche Analyse müssen die Begleitdateien bzw. der Projektkontext mitausgewertet werden."
        )

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
