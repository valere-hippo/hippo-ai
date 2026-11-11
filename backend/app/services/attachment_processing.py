from __future__ import annotations

import base64
import binascii
import re
import struct
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


def _extract_text_from_xlsx(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            shared_strings: list[str] = []
            try:
                shared_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for node in shared_xml.findall(".//a:si", ns):
                    text_parts = [part.text for part in node.findall(".//a:t", ns) if part.text]
                    shared_strings.append("".join(text_parts))
            except Exception:
                shared_strings = []

            sheet_names: list[tuple[str, str]] = []
            try:
                workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
                ns = {
                    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                }
                sheets = workbook_xml.findall(".//a:sheets/a:sheet", ns)
                rels = {}
                try:
                    rels_xml = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
                    for rel in rels_xml.findall(".//r:Relationship", rel_ns):
                        rels[rel.attrib.get("Id", "")] = rel.attrib.get("Target", "")
                except Exception:
                    rels = {}
                for sheet in sheets[:4]:
                    name = sheet.attrib.get("name", "Tabelle")
                    rel_id = sheet.attrib.get(f"{{{ns['r']}}}id", "")
                    target = rels.get(rel_id, "")
                    if target and not target.startswith("/"):
                        target = f"xl/{target.lstrip('/') }"
                    if target:
                        sheet_names.append((name, target))
            except Exception:
                sheet_names = []

            parts: list[str] = []
            if not sheet_names:
                sheet_names = [("Tabelle1", "xl/worksheets/sheet1.xml")]

            ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for sheet_name, target in sheet_names[:4]:
                try:
                    sheet_xml = ET.fromstring(archive.read(target))
                except Exception:
                    continue
                rows: list[str] = []
                for row in sheet_xml.findall(".//a:sheetData/a:row", ns)[:8]:
                    values: list[str] = []
                    for cell in row.findall(".//a:c", ns)[:16]:
                        value = ""
                        cell_type = cell.attrib.get("t", "")
                        cell_value = cell.findtext("a:v", default="", namespaces=ns) or ""
                        if cell_type == "s":
                            try:
                                value = shared_strings[int(cell_value)]
                            except Exception:
                                value = cell_value
                        elif cell_type == "inlineStr":
                            value = "".join(part.text for part in cell.findall(".//a:t", ns) if part.text)
                        else:
                            value = cell_value
                        value = re.sub(r"\s+", " ", str(value or "")).strip()
                        if value:
                            values.append(value)
                    if values:
                        rows.append(" | ".join(values))
                if rows:
                    parts.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows))
            return _truncate("\n\n".join(parts))
    except (BadZipFile, KeyError, OSError):
        return ""
    except Exception:
        return ""
    return ""


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


SHAPE_TYPE_NAMES = {
    0: "Null Shape",
    1: "Point",
    3: "PolyLine",
    5: "Polygon",
    8: "MultiPoint",
    11: "PointZ",
    13: "PolyLineZ",
    15: "PolygonZ",
    18: "MultiPointZ",
    21: "PointM",
    23: "PolyLineM",
    25: "PolygonM",
    28: "MultiPointM",
    31: "MultiPatch",
}


def _decode_text_bytes(data: bytes, encodings: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")) -> str:
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            return text
    return ""


def _shape_type_name(shape_type: int | None) -> str:
    try:
        if shape_type is None:
            return "Unknown"
        shape_value = int(shape_type)
        return SHAPE_TYPE_NAMES.get(shape_value, f"Unknown ({shape_value})")
    except Exception:
        return "Unknown"


def _parse_shapefile_header(data: bytes) -> dict[str, Any]:
    if len(data) < 100:
        return {}
    try:
        file_code = struct.unpack(">i", data[0:4])[0]
        file_length_words = struct.unpack(">i", data[24:28])[0]
        version = struct.unpack("<i", data[28:32])[0]
        shape_type = struct.unpack("<i", data[32:36])[0]
        xmin, ymin, xmax, ymax = struct.unpack("<4d", data[36:68])
        return {
            "file_code": file_code,
            "file_length_words": file_length_words,
            "version": version,
            "shape_type": shape_type,
            "bbox": (xmin, ymin, xmax, ymax),
        }
    except Exception:
        return {}


def _format_bbox(bbox: tuple[float, float, float, float] | None) -> str:
    if not bbox:
        return ""
    return f"{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}"


def _parse_dbf_bytes(data: bytes, encoding: str | None = None, max_rows: int = 3) -> dict[str, Any]:
    if len(data) < 32:
        return {}
    try:
        num_records = struct.unpack("<I", data[4:8])[0]
        header_length = struct.unpack("<H", data[8:10])[0]
        record_length = struct.unpack("<H", data[10:12])[0]
    except Exception:
        return {}

    fields: list[dict[str, Any]] = []
    offset = 32
    while offset + 32 <= len(data):
        if data[offset] == 0x0D:
            offset += 1
            break
        descriptor = data[offset:offset + 32]
        raw_name = descriptor[0:11].split(b"\x00", 1)[0].strip()
        field_name = raw_name.decode("ascii", errors="ignore").strip()
        field_type = chr(descriptor[11]) if descriptor[11] else "?"
        field_length = descriptor[16]
        decimal_count = descriptor[17]
        if field_name:
            fields.append({"name": field_name, "type": field_type, "length": field_length, "decimal_count": decimal_count})
        offset += 32

    encoding_name = (encoding or "cp1252").strip() or "cp1252"
    rows: list[dict[str, str]] = []
    try:
        row_offset = max(header_length, offset)
        for _index in range(min(max_rows, num_records)):
            if row_offset + record_length > len(data):
                break
            record = data[row_offset:row_offset + record_length]
            row_offset += record_length
            if not record or record[0:1] == b"*":
                continue
            cursor = 1
            row: dict[str, str] = {}
            for field in fields:
                length = int(field.get("length") or 0)
                raw_value = record[cursor:cursor + length]
                cursor += length
                value = raw_value.decode(encoding_name, errors="replace").strip("\x00 \t\r\n")
                if value:
                    row[field["name"]] = value
            if row:
                rows.append(row)
            if len(rows) >= max_rows:
                break
    except Exception:
        pass

    return {
        "num_records": num_records,
        "header_length": header_length,
        "record_length": record_length,
        "fields": fields,
        "rows": rows,
    }


def _extract_geo_bundle_context(attachments: list[Any], filename: str) -> str:
    related_names = _attachment_related_geo_names(filename)
    related_map = _attachment_group_map(attachments)
    related_attachments = [related_map.get(name.lower()) for name in related_names if related_map.get(name.lower())]
    if not related_attachments:
        return ""

    stem = _attachment_stem(filename)
    parts = [f"Geodatenpaket für '{stem}':"]
    parts.append("- Enthaltene Dateien: " + ", ".join(_attachment_name(att) for att in related_attachments))

    cpg_text = ""
    prj_text = ""
    shp_summary: dict[str, Any] = {}
    shx_summary: dict[str, Any] = {}
    dbf_summary: dict[str, Any] = {}

    for att in related_attachments:
        att_name = _attachment_name(att)
        data = _decode_attachment_bytes(att)
        if not data:
            continue
        lower = att_name.lower()
        if lower.endswith(".cpg"):
            cpg_text = _decode_text_bytes(data)
        elif lower.endswith(".prj"):
            prj_text = _decode_text_bytes(data)
        elif lower.endswith(".shp"):
            shp_summary = _parse_shapefile_header(data)
        elif lower.endswith(".shx"):
            shx_summary = _parse_shapefile_header(data)
        elif lower.endswith(".dbf"):
            dbf_summary = _parse_dbf_bytes(data, encoding=cpg_text or None)

    if shp_summary:
        parts.append(f"- SHP: Datei-Code {shp_summary.get('file_code')}, Version {shp_summary.get('version')}, Geometrietyp {_shape_type_name(shp_summary.get('shape_type'))}")
        bbox_text = _format_bbox(shp_summary.get('bbox'))
        if bbox_text:
            parts.append(f"- Bounding Box: {bbox_text}")

    if shx_summary:
        parts.append(f"- SHX: Datei-Code {shx_summary.get('file_code')}, Version {shx_summary.get('version')}, Geometrietyp {_shape_type_name(shx_summary.get('shape_type'))}")
        bbox_text = _format_bbox(shx_summary.get('bbox'))
        if bbox_text and bbox_text != _format_bbox(shp_summary.get('bbox')):
            parts.append(f"- SHX Bounding Box: {bbox_text}")

    if dbf_summary:
        parts.append(f"- DBF: {dbf_summary.get('num_records', 0)} Datensatz{'e' if int(dbf_summary.get('num_records', 0) or 0) != 1 else ''}, {len(dbf_summary.get('fields', []))} Felder")
        fields = dbf_summary.get('fields') or []
        if fields:
            parts.append(
                "- Felder: " + ", ".join(
                    f"{field.get('name')} ({field.get('type')}, {field.get('length')})"
                    for field in fields[:12]
                    if field.get('name')
                )
            )
        rows = dbf_summary.get('rows') or []
        if rows:
            sample = rows[0]
            sample_text = ", ".join(f"{key}={value}" for key, value in list(sample.items())[:8])
            if sample_text:
                parts.append(f"- Beispielzeile: {sample_text}")

    if cpg_text:
        parts.append(f"- CPG/Encoding: {cpg_text}")
    if prj_text:
        parts.append(f"- Projektion: {prj_text}")

    if len(parts) == 2:
        parts.append("- Geodatenpaket erkannt, aber nur begrenzt auslesbare Inhalte gefunden.")

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

    if (
        mime_type
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        or lower_name.endswith(".xlsx")
    ):
        return _extract_text_from_xlsx(data)

    if mime_type.startswith("image/") or lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")):
        return _extract_text_from_image(data)

    if mime_type.startswith("text/") or lower_name.endswith((".txt", ".md", ".csv", ".log", ".rtf")):
        return _extract_text_from_plain_text(data)

    if lower_name.endswith(".cpg"):
        encoding = _decode_text_bytes(data) or "unbekannt"
        return _truncate(f"[Geodaten-Datei: {filename}] Encoding/CPG: {encoding}")

    if lower_name.endswith(".prj"):
        projection = _decode_text_bytes(data) or "unbekannt"
        return _truncate(f"[Geodaten-Datei: {filename}] Projektion/PRJ: {projection}")

    if lower_name.endswith(".dbf"):
        summary = _parse_dbf_bytes(data)
        if summary:
            fields = summary.get("fields") or []
            rows = summary.get("rows") or []
            parts = [f"[Geodaten-Datei: {filename}] DBF-Attributtabelle"]
            parts.append(f"Datensatz{'e' if int(summary.get('num_records', 0) or 0) != 1 else ''}: {summary.get('num_records', 0)}")
            if fields:
                parts.append("Felder: " + ", ".join(f"{field.get('name')} ({field.get('type')}, {field.get('length')})" for field in fields[:12] if field.get('name')))
            if rows:
                sample = rows[0]
                sample_text = ", ".join(f"{key}={value}" for key, value in list(sample.items())[:8])
                if sample_text:
                    parts.append(f"Beispielzeile: {sample_text}")
            return _truncate("\n".join(parts))
        return _truncate(f"[Geodaten-Datei: {filename}] DBF-Datei erkannt, aber keine Attributdaten gelesen.")

    if lower_name.endswith((".shp", ".shx")):
        summary = _parse_shapefile_header(data)
        if summary:
            parts = [f"[Geodaten-Datei: {filename}] Shapefile-Header"]
            parts.append(f"Datei-Code: {summary.get('file_code')}")
            parts.append(f"Version: {summary.get('version')}")
            parts.append(f"Geometrietyp: {_shape_type_name(summary.get('shape_type'))}")
            bbox_text = _format_bbox(summary.get('bbox'))
            if bbox_text:
                parts.append(f"Bounding Box: {bbox_text}")
            return _truncate("\n".join(parts))
        return _truncate(f"[Geodaten-Datei: {filename}] Geodaten-Header erkannt, aber nicht vollständig auslesbar.")

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
    file_path = (getattr(attachment, "file_path", None) or "").strip()
    if file_path:
        lines.append(f"[Local path] {file_path}")
    if extracted_text:
        lines.append("[Content]")
        lines.append(extracted_text)
    elif mime_type.startswith("image/") or filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        lines.append(f"[Image metadata] {_image_metadata(_decode_attachment_bytes(attachment))}")
    return "\n".join(lines)
