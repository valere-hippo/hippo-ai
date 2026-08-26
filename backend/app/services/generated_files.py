from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import re
import html
from xml.sax.saxutils import escape as xml_escape

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    Image = ImageDraw = ImageFont = None


FILE_MARKER_RE = re.compile(
    r"<<<FILE:(?P<filename>[^>]+)>>>\s*(?P<content>[\s\S]*?)\s*<<<END_FILE>>>",
    re.IGNORECASE,
)


@dataclass
class GeneratedFile:
    filename: str
    content: str


def extract_generated_files(text: str) -> tuple[list[GeneratedFile], str]:
    files: list[GeneratedFile] = []

    def _replace(match: re.Match[str]) -> str:
        files.append(
            GeneratedFile(
                filename=match.group("filename").strip(),
                content=match.group("content").strip(),
            )
        )
        return ""

    cleaned = FILE_MARKER_RE.sub(_replace, text or "").strip()
    return files, cleaned


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
    )


def build_simple_pdf_bytes(title: str, body: str) -> bytes:
    lines = [title.strip()] if title.strip() else []
    lines.extend((body or "").replace("\r", "").split("\n"))

    wrapped_lines: list[str] = []
    for line in lines:
        if not line:
            wrapped_lines.append("")
            continue
        text = line
        while len(text) > 90:
            wrapped_lines.append(text[:90])
            text = text[90:]
        wrapped_lines.append(text)

    if not wrapped_lines:
        wrapped_lines = [" "]

    content_lines = ["BT", "/F1 12 Tf", "72 760 Td"]
    first = True
    for line in wrapped_lines:
        safe = _pdf_escape(line)
        if first:
            content_lines.append(f"({safe}) Tj")
            first = False
        else:
            content_lines.append("T*")
            content_lines.append(f"({safe}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("utf-8")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(
        f"<< /Length {len(content)} >>\nstream\n".encode("utf-8")
        + content
        + b"\nendstream"
    )

    buffer = BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("utf-8"))
        buffer.write(obj)
        buffer.write(b"\nendobj\n")

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("utf-8"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("utf-8"))
    buffer.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("utf-8")
    )
    return buffer.getvalue()


def _rtf_escape(text: str) -> str:
    escaped = []
    for char in text:
        code = ord(char)
        if char == "\\":
            escaped.append("\\\\")
        elif char == "{":
            escaped.append("\\{")
        elif char == "}":
            escaped.append("\\}")
        elif code > 127:
            escaped.append(f"\\u{code}?")
        else:
            escaped.append(char)
    return "".join(escaped)


def build_rtf_bytes(title: str, body: str) -> bytes:
    lines = [title.strip()] if title.strip() else []
    lines.extend((body or "").replace("\r", "").split("\n"))
    body_lines = []
    for line in lines:
        body_lines.append(_rtf_escape(line))
        body_lines.append("\\par ")
    content = "".join(body_lines) or "\\par "
    rtf = r"{\rtf1\ansi\deff0{\fonttbl{\f0 Arial;}}\fs24 " + content + "}"
    return rtf.encode("utf-8")


def build_docx_bytes(title: str, body: str) -> bytes:
    paragraphs = [title.strip()] if title.strip() else []
    paragraphs.extend((body or "").replace("\r", "").split("\n"))
    paragraphs = [line for line in paragraphs if line is not None]

    doc_xml_paragraphs = []
    for paragraph in paragraphs or [""]:
        safe = xml_escape(paragraph)
        doc_xml_paragraphs.append(
            f"<w:p><w:r><w:t xml:space=\"preserve\">{safe}</w:t></w:r></w:p>"
        )

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>"
        + "".join(doc_xml_paragraphs)
        + "<w:sectPr><w:pgSz w:w=\"12240\" w:h=\"15840\"/></w:sectPr>"
        "</w:body></w:document>"
    )

    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>"
    )

    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"R1\" "
        "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
        "Target=\"word/document.xml\"/>"
        "</Relationships>"
    )

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr(
            "word/_rels/document.xml.rels",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"/>",
        )
        zf.writestr(
            "docProps/app.xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" "
            "xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\">"
            "<Application>Hippo AI</Application></Properties>",
        )
        zf.writestr(
            "docProps/core.xml",
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
            "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
            "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" "
            "xmlns:dcterms=\"http://purl.org/dc/terms/\" "
            "xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" "
            "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
            f"<dc:title>{xml_escape(title or 'Hippo AI Document')}</dc:title>"
            "</cp:coreProperties>",
        )
    return buffer.getvalue()


def _render_svg_text(title: str, body: str) -> str:
    safe_title = html.escape(title or "Hippo AI")
    lines = (body or "").replace("\r", "").split("\n")
    text_lines = [safe_title]
    text_lines.extend([part for part in lines if part])
    if len(text_lines) == 1:
        text_lines.append("Generated by Hippo AI")

    line_nodes = []
    y = 72
    for line in text_lines[:28]:
        line_nodes.append(
            f"<text x=\"40\" y=\"{y}\" font-family=\"Space Grotesk, Arial, sans-serif\" "
            f"font-size=\"24\" fill=\"#edf4fb\">{html.escape(line)}</text>"
        )
        y += 34

    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1200\" height=\"800\" viewBox=\"0 0 1200 800\">"
        "<defs>"
        "<linearGradient id=\"g\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">"
        "<stop offset=\"0%\" stop-color=\"#63d7bf\"/>"
        "<stop offset=\"100%\" stop-color=\"#9ab2ff\"/>"
        "</linearGradient>"
        "</defs>"
        "<rect width=\"1200\" height=\"800\" fill=\"#0a1016\"/>"
        "<circle cx=\"1040\" cy=\"120\" r=\"170\" fill=\"url(#g)\" opacity=\"0.14\"/>"
        "<rect x=\"24\" y=\"24\" width=\"1152\" height=\"752\" rx=\"36\" fill=\"#111a25\" stroke=\"rgba(255,255,255,0.08)\"/>"
        "<rect x=\"40\" y=\"40\" width=\"200\" height=\"48\" rx=\"16\" fill=\"rgba(99,215,191,0.16)\"/>"
        "<text x=\"56\" y=\"72\" font-family=\"Space Grotesk, Arial, sans-serif\" font-size=\"20\" fill=\"#63d7bf\">Hippo AI</text>"
        + "".join(line_nodes)
        + "</svg>"
    )


def build_svg_bytes(title: str, body: str) -> bytes:
    return _render_svg_text(title, body).encode("utf-8")


def _wrap_text(draw: "ImageDraw.ImageDraw", text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def build_raster_image_bytes(title: str, body: str, format_name: str) -> bytes:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow is required to generate raster images.")

    width, height = 1400, 900
    img = Image.new("RGB", (width, height), "#0a1016")
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(10 + ratio * 16)
        g = int(16 + ratio * 22)
        b = int(22 + ratio * 26)
        draw.line((0, y, width, y), fill=(r, g, b))

    for box, color in (
        ((40, 40, width - 40, height - 40), (24, 35, 49)),
        ((70, 70, 400, 140), (99, 215, 191)),
    ):
        draw.rounded_rectangle(box, radius=28, fill=color)

    draw.rounded_rectangle((40, 40, width - 40, height - 40), radius=36, outline=(255, 255, 255), width=2)

    title_font = ImageFont.load_default()
    body_font = ImageFont.load_default()

    title_text = (title or "Hippo AI").strip()
    body_text = (body or "").strip()
    header_color = "#081118"
    draw.text((98, 92), "Hippo AI", fill=header_color, font=title_font)

    wrapped_title = _wrap_text(draw, title_text, title_font, 1200)
    y = 180
    for line in wrapped_title[:4]:
        draw.text((96, y), line, fill="#edf4fb", font=title_font)
        y += 28

    if body_text:
        y += 24
        wrapped_body = _wrap_text(draw, body_text, body_font, 1240)
        for line in wrapped_body[:26]:
            draw.text((96, y), line, fill="#c9d7e6", font=body_font)
            y += 22

    footer = f"Generated by Hippo AI · {format_name.upper()}"
    draw.text((96, height - 72), footer, fill="#63d7bf", font=body_font)

    buffer = BytesIO()
    save_format = "JPEG" if format_name.lower() in {"jpg", "jpeg"} else "PNG"
    if save_format == "JPEG":
        img = img.convert("RGB")
        img.save(buffer, format=save_format, quality=92, optimize=True)
    else:
        img.save(buffer, format=save_format, optimize=True)
    return buffer.getvalue()


def save_generated_file(folder: str, filename: str, content: str) -> str:
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    base_title = Path(safe_name).stem.replace("_", " ").strip() or "Hippo AI"
    body = content.strip()

    target = Path(folder) / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".docx":
        target.write_bytes(build_docx_bytes(base_title, body))
    elif ext == ".pdf":
        target.write_bytes(build_simple_pdf_bytes(base_title, body))
    elif ext == ".rtf":
        target.write_bytes(build_rtf_bytes(base_title, body))
    elif ext == ".svg":
        target.write_bytes(build_svg_bytes(base_title, body))
    elif ext in {".png", ".jpg", ".jpeg"}:
        target.write_bytes(build_raster_image_bytes(base_title, body, ext.lstrip(".")))
    else:
        target.write_text(body, encoding="utf-8")

    return str(target)
