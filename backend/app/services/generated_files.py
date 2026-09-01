from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import struct
import re
import html
import mimetypes
import math
import textwrap
import unicodedata
import zlib
from xml.sax.saxutils import escape as xml_escape

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    Image = ImageDraw = ImageFont = None


FILE_START_RE = re.compile(r"<<<FILE:(?P<filename>[^>]+)>>>", re.IGNORECASE)
FILE_END_RE = re.compile(r"<<<END_FILE>>>", re.IGNORECASE)


@dataclass
class GeneratedFile:
    filename: str
    content: str


@dataclass
class ReportLine:
    kind: str
    text: str
    level: int = 0


def _strip_inline_markup(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)
    cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
    cleaned = re.sub(r"_(.+?)_", r"\1", cleaned)
    cleaned = re.sub(r"`(.+?)`", r"\1", cleaned)
    return cleaned.strip()


def _normalize_report_text(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in (text or "").replace("\r", "").split("\n"):
        line = raw_line.strip()
        if line.startswith("```"):
            continue
        line = line.replace("\u00a0", " ")
        lines.append(line)
    return lines


def _parse_report_blocks(text: str) -> list[ReportLine]:
    blocks: list[ReportLine] = []
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_buffer:
            blocks.append(ReportLine(kind="paragraph", text=" ".join(paragraph_buffer).strip()))
            paragraph_buffer.clear()

    for index, line in enumerate(_normalize_report_text(text)):
        if not line:
            flush_paragraph()
            continue

        if re.fullmatch(r"[-–—]{3,}", line):
            flush_paragraph()
            blocks.append(ReportLine(kind="rule", text=""))
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            flush_paragraph()
            blocks.append(
                ReportLine(
                    kind="heading",
                    text=_strip_inline_markup(heading_match.group(2)),
                    level=len(heading_match.group(1)),
                )
            )
            continue

        if index == 0:
            candidate = _strip_inline_markup(line)
            if candidate and len(candidate) <= 100:
                blocks.append(ReportLine(kind="title", text=candidate, level=0))
                continue

        if re.match(r"^\*[^*].*\*$", line) or re.match(r"^_[^_].*_$", line):
            flush_paragraph()
            blocks.append(ReportLine(kind="subtitle", text=_strip_inline_markup(line), level=0))
            continue

        bullet_match = re.match(r"^([-*•])\s+(.+)$", line)
        if bullet_match:
            flush_paragraph()
            blocks.append(ReportLine(kind="bullet", text=_strip_inline_markup(bullet_match.group(2)), level=0))
            continue

        numbered_match = re.match(r"^(\d+[.)])\s+(.+)$", line)
        if numbered_match:
            flush_paragraph()
            blocks.append(ReportLine(kind="numbered", text=_strip_inline_markup(numbered_match.group(2)), level=0))
            continue

        if "|" in line and not re.fullmatch(r"\|?[-:\s|]+\|?", line):
            flush_paragraph()
            blocks.append(ReportLine(kind="tableline", text=_strip_inline_markup(line), level=0))
            continue

        paragraph_buffer.append(_strip_inline_markup(line))

    flush_paragraph()
    return blocks


def extract_generated_files(text: str) -> tuple[list[GeneratedFile], str]:
    files: list[GeneratedFile] = []
    source = text or ""
    cleaned_parts: list[str] = []
    cursor = 0

    while True:
        start_match = FILE_START_RE.search(source, cursor)
        if not start_match:
            cleaned_parts.append(source[cursor:])
            break

        cleaned_parts.append(source[cursor:start_match.start()])
        filename = start_match.group("filename").strip()
        content_start = start_match.end()

        end_match = FILE_END_RE.search(source, content_start)
        next_start = FILE_START_RE.search(source, content_start)

        if end_match and (not next_start or end_match.start() <= next_start.start()):
            content = source[content_start:end_match.start()]
            cursor = end_match.end()
        elif next_start:
            content = source[content_start:next_start.start()]
            cursor = next_start.start()
        else:
            content = source[content_start:]
            cursor = len(source)

        files.append(
            GeneratedFile(
                filename=filename,
                content=content.strip(),
            )
        )

    cleaned = "".join(cleaned_parts).strip()
    return files, cleaned


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
    )


def _pdf_text_bytes(text: str) -> bytes:
    # PDF viewers generally expect text in a single-byte encoding for Base14 fonts.
    # Windows-1252 preserves German umlauts and ß, which fixes mojibake in report PDFs.
    return _pdf_escape(text).encode("cp1252", errors="replace")


def build_simple_pdf_bytes(title: str, body: str) -> bytes:
    def make_line(text: str, font: str, size: int, x: int, y: int) -> bytes:
        return (
            f"BT /{font} {size} Tf 1 0 0 1 {x} {y} Tm (".encode("ascii")
            + _pdf_text_bytes(text)
            + b") Tj ET"
        )

    def wrap_text(text: str, max_chars: int) -> list[str]:
        wrapped: list[str] = []
        for paragraph in (text or "").split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                wrapped.append("")
                continue
            wrapped.extend(
                textwrap.wrap(
                    paragraph,
                    width=max_chars,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or [paragraph]
            )
        return wrapped or [""]

    blocks = _parse_report_blocks(body)
    title_text = (title or "Hippo AI Document").strip()
    if blocks and blocks[0].kind == "title":
        title_text = blocks[0].text
        blocks = blocks[1:]

    pages: list[list[str]] = []
    current_page: list[bytes] = []
    y = 740

    def new_page() -> None:
        nonlocal current_page, y
        if current_page:
            pages.append(current_page)
        current_page = []
        y = 740

    def add_line(text: str, font: str = "Helvetica", size: int = 12, indent: int = 0, gap_after: int = 4) -> None:
        nonlocal y
        line_height = max(16, int(size * 1.45))
        if y - line_height < 72:
            new_page()
        current_page.append(make_line(text, font, size, 72 + indent, y))
        y -= line_height + gap_after

    def add_wrapped(text: str, font: str = "Helvetica", size: int = 12, indent: int = 0, max_chars: int = 90, gap_after: int = 2) -> None:
        wrapped = wrap_text(text, max_chars=max_chars)
        for idx, part in enumerate(wrapped):
            if part == "":
                add_line("", font=font, size=size, indent=indent, gap_after=6)
                continue
            add_line(part, font=font, size=size, indent=indent, gap_after=gap_after if idx < len(wrapped) - 1 else 8)

    # Title page header
    add_line(title_text, font="Helvetica-Bold", size=22, indent=0, gap_after=6)
    add_line("Bericht", font="Helvetica", size=11, indent=0, gap_after=10)
    current_page.append(b"BT 0.10 0.49 0.44 rg 72 708 445 2 re f ET")
    y -= 18

    for block in blocks:
        if block.kind == "subtitle":
            add_wrapped(block.text, font="Helvetica-Oblique", size=10, indent=0, max_chars=86, gap_after=6)
        elif block.kind == "heading":
            size = 16 if block.level <= 2 else 13
            add_wrapped(block.text, font="Helvetica-Bold", size=size, indent=0, max_chars=78, gap_after=4)
        elif block.kind == "bullet":
            add_wrapped(f"• {block.text}", font="Helvetica", size=11, indent=18, max_chars=82, gap_after=2)
        elif block.kind == "numbered":
            add_wrapped(f"{block.text}", font="Helvetica", size=11, indent=18, max_chars=82, gap_after=2)
        elif block.kind == "tableline":
            cleaned = re.sub(r"\s*\|\s*", "   ", block.text)
            add_wrapped(cleaned, font="Helvetica", size=10, indent=10, max_chars=86, gap_after=2)
        elif block.kind == "rule":
            current_page.append(
                f"BT /Helvetica 10 Tf 1 0 0 1 72 {y} Tm (____________________________________________) Tj ET".encode(
                    "ascii"
                )
            )
            y -= 16
        else:
            add_wrapped(block.text, font="Helvetica", size=12, indent=0, max_chars=88, gap_after=2)

    pages.append(current_page)

    buffer = BytesIO()
    buffer.write(b"%PDF-1.4\n")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    page_count = max(1, len(pages))
    page_object_numbers = [6 + (index * 2) for index in range(page_count)]
    kids = " ".join(f"{page_no} 0 R" for page_no in page_object_numbers)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("utf-8"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>")

    for index in range(page_count):
        page_lines = pages[index] if index < len(pages) else []
        page_obj_num = 6 + (index * 2)
        content_obj_num = page_obj_num + 1
        content = b"\n".join(page_lines)
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents {content_obj_num} 0 R >>"
        ).encode("ascii")
        objects.append(page_obj)
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream"
        )

    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("ascii"))
        buffer.write(obj)
        buffer.write(b"\nendobj\n")

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.write(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            "startxref\n"
            f"{xref_offset}\n"
            "%%EOF\n"
        ).encode("ascii")
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
    blocks = _parse_report_blocks(body)
    title_text = (title or "Hippo AI Document").strip()
    if blocks and blocks[0].kind == "title":
        title_text = blocks[0].text
        blocks = blocks[1:]

    def run_xml(text: str, *, bold: bool = False, italic: bool = False, size: int | None = None, color: str | None = None) -> str:
        attrs = []
        if size is not None:
            attrs.append(f"<w:sz w:val=\"{size}\"/>")
        if bold:
            attrs.append("<w:b/>")
        if italic:
            attrs.append("<w:i/>")
        if color:
            attrs.append(f"<w:color w:val=\"{color}\"/>")
        safe = xml_escape(text)
        return f"<w:r><w:rPr>{''.join(attrs)}</w:rPr><w:t xml:space=\"preserve\">{safe}</w:t></w:r>"

    def paragraph_xml(runs: list[str], *, align: str | None = None, left: int | None = None, before: int | None = None, after: int | None = None) -> str:
        props = []
        if align:
            props.append(f"<w:jc w:val=\"{align}\"/>")
        if left is not None:
            props.append(f"<w:ind w:left=\"{left}\"/>")
        if before is not None or after is not None:
            attrs = []
            if before is not None:
                attrs.append(f"w:before=\"{before}\"")
            if after is not None:
                attrs.append(f"w:after=\"{after}\"")
            props.append(f"<w:spacing {' '.join(attrs)}/>")
        prop_xml = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
        return f"<w:p>{prop_xml}{''.join(runs)}</w:p>"

    doc_xml_paragraphs: list[str] = [
        paragraph_xml(
            [run_xml(title_text, bold=True, size=32, color="1B2A36")],
            align="center",
            after=120,
        ),
        paragraph_xml(
            [run_xml("Professioneller Bericht", italic=True, size=20, color="5F7283")],
            align="center",
            after=240,
        ),
    ]

    for block in blocks:
        if block.kind == "subtitle":
            doc_xml_paragraphs.append(
                paragraph_xml(
                    [run_xml(block.text, italic=True, size=20, color="5F7283")],
                    after=180,
                )
            )
        elif block.kind == "heading":
            size = 26 if block.level <= 2 else 22
            doc_xml_paragraphs.append(
                paragraph_xml(
                    [run_xml(block.text, bold=True, size=size, color="163C4F")],
                    before=180,
                    after=120,
                )
            )
        elif block.kind == "bullet":
            doc_xml_paragraphs.append(
                paragraph_xml(
                    [run_xml(f"• {block.text}", size=22)],
                    left=480,
                    after=60,
                )
            )
        elif block.kind == "numbered":
            doc_xml_paragraphs.append(
                paragraph_xml(
                    [run_xml(block.text, size=22)],
                    left=480,
                    after=60,
                )
            )
        elif block.kind == "tableline":
            doc_xml_paragraphs.append(
                paragraph_xml(
                    [run_xml(re.sub(r"\s*\|\s*", "   ", block.text), size=20)],
                    left=180,
                    after=40,
                )
            )
        elif block.kind == "rule":
            doc_xml_paragraphs.append(
                paragraph_xml([run_xml("────────────────────────────────────────", size=18, color="CBD7E2")], after=120)
            )
        else:
            doc_xml_paragraphs.append(
                paragraph_xml([run_xml(block.text, size=22)], after=80)
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


def _png_chunk(name: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + name
        + payload
        + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
    )


def _encode_png_rgba(width: int, height: int, pixels: bytearray) -> bytes:
    raw = bytearray()
    row_width = width * 4
    for row in range(height):
        raw.append(0)
        start = row * row_width
        raw.extend(pixels[start : start + row_width])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _blend_pixel(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int], alpha: int = 255) -> None:
    if x < 0 or y < 0:
        return
    height = len(pixels) // (width * 4)
    if x >= width or y >= height:
        return
    idx = (y * width + x) * 4
    src_alpha = max(0, min(255, alpha)) / 255.0
    inv_alpha = 1.0 - src_alpha
    pixels[idx] = int(color[0] * src_alpha + pixels[idx] * inv_alpha)
    pixels[idx + 1] = int(color[1] * src_alpha + pixels[idx + 1] * inv_alpha)
    pixels[idx + 2] = int(color[2] * src_alpha + pixels[idx + 2] * inv_alpha)
    pixels[idx + 3] = 255


def _fill_rect(
    pixels: bytearray,
    width: int,
    x: int,
    y: int,
    w: int,
    h: int,
    color: tuple[int, int, int],
    alpha: int = 255,
) -> None:
    if w <= 0 or h <= 0:
        return
    for yy in range(max(0, y), min(y + h, len(pixels) // (width * 4))):
        for xx in range(max(0, x), min(x + w, width)):
            _blend_pixel(pixels, width, xx, yy, color, alpha)


def _draw_line(
    pixels: bytearray,
    width: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    alpha: int = 255,
    thickness: int = 1,
) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        half = max(0, thickness // 2)
        for off_y in range(-half, half + 1):
            for off_x in range(-half, half + 1):
                _blend_pixel(pixels, width, x0 + off_x, y0 + off_y, color, alpha)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _draw_radial_glow(
    pixels: bytearray,
    width: int,
    cx: int,
    cy: int,
    radius: int,
    color: tuple[int, int, int],
    max_alpha: int,
) -> None:
    height = len(pixels) // (width * 4)
    x0 = max(0, cx - radius)
    y0 = max(0, cy - radius)
    x1 = min(width - 1, cx + radius)
    y1 = min(height - 1, cy + radius)
    radius_sq = radius * radius
    for yy in range(y0, y1 + 1):
        dy_sq = (yy - cy) * (yy - cy)
        for xx in range(x0, x1 + 1):
            dist_sq = (xx - cx) * (xx - cx) + dy_sq
            if dist_sq > radius_sq:
                continue
            ratio = 1.0 - (dist_sq / radius_sq)
            alpha = int(max_alpha * ratio * ratio)
            if alpha > 0:
                _blend_pixel(pixels, width, xx, yy, color, alpha)


def _normalize_ascii(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.replace("ß", "ss")
    normalized = normalized.encode("ascii", "ignore").decode("ascii", errors="ignore")
    return normalized


def _build_fallback_png_bytes(title: str, body: str) -> bytes:
    width, height = 1280, 720
    pixels = bytearray(width * height * 4)

    top = (10, 18, 30)
    middle = (17, 28, 42)
    bottom = (6, 10, 16)
    for yy in range(height):
        ratio = yy / max(1, height - 1)
        if ratio < 0.52:
            span = ratio / 0.52
            r = int(top[0] + (middle[0] - top[0]) * span)
            g = int(top[1] + (middle[1] - top[1]) * span)
            b = int(top[2] + (middle[2] - top[2]) * span)
        else:
            span = (ratio - 0.52) / 0.48
            r = int(middle[0] + (bottom[0] - middle[0]) * span)
            g = int(middle[1] + (bottom[1] - middle[1]) * span)
            b = int(middle[2] + (bottom[2] - middle[2]) * span)
        row = bytes((r, g, b, 255)) * width
        start = yy * width * 4
        pixels[start : start + width * 4] = row

    # Subtle atmospheric glow.
    _draw_radial_glow(pixels, width, 260, 150, 280, (91, 157, 255), 70)
    _draw_radial_glow(pixels, width, 980, 110, 260, (99, 215, 191), 55)
    _draw_radial_glow(pixels, width, 640, 340, 240, (255, 214, 120), 120)
    _draw_radial_glow(pixels, width, 640, 340, 120, (255, 245, 222), 170)

    # Light rays from the center.
    ray_color = (255, 232, 170)
    for target in ((120, 80), (1110, 80), (40, 330), (1240, 320), (220, 620), (1040, 620)):
        _draw_line(pixels, width, 640, 340, target[0], target[1], ray_color, alpha=30, thickness=3)

    # Dark cloud bands near the top and bottom for contrast.
    _fill_rect(pixels, width, 0, 0, width, 130, (6, 10, 16), 110)
    _fill_rect(pixels, width, 0, 630, width, 90, (5, 8, 13), 150)

    # Halo and cross theme, with a gentle highlight.
    _draw_radial_glow(pixels, width, 640, 340, 210, (255, 214, 120), 140)
    _fill_rect(pixels, width, 609, 170, 62, 340, (255, 223, 129), 235)
    _fill_rect(pixels, width, 500, 286, 280, 52, (255, 223, 129), 235)
    _fill_rect(pixels, width, 623, 182, 36, 316, (255, 250, 234), 90)
    _fill_rect(pixels, width, 509, 295, 262, 34, (255, 250, 234), 90)
    _draw_radial_glow(pixels, width, 640, 332, 68, (255, 255, 255), 100)

    # Ground silhouette.
    _fill_rect(pixels, width, 0, 610, width, 110, (4, 7, 12), 210)
    _draw_radial_glow(pixels, width, 280, 660, 240, (13, 19, 27), 170)
    _draw_radial_glow(pixels, width, 980, 662, 260, (13, 19, 27), 170)

    # Framing accent.
    _fill_rect(pixels, width, 42, 42, width - 84, height - 84, (255, 255, 255), 18)
    _fill_rect(pixels, width, 54, 54, width - 108, height - 108, (18, 27, 39), 180)
    _fill_rect(pixels, width, 70, 70, 220, 42, (99, 215, 191), 150)

    # Use the text to subtly influence the warmth of the scene.
    normalized = _normalize_ascii(f"{title}\n{body}").upper()
    if any(keyword in normalized for keyword in ("JESUS", "CHRIST", "CROSS", "PUISSANT", "POWER", "DIVINE")):
        _draw_radial_glow(pixels, width, 640, 340, 320, (255, 199, 92), 65)
    else:
        _draw_radial_glow(pixels, width, 640, 340, 320, (154, 178, 255), 50)

    return _encode_png_rgba(width, height, pixels)


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


def _load_font(size: int, bold: bool = False):
    if ImageFont is None:
        return None
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _topic_key(title: str, body: str) -> str:
    normalized = _normalize_ascii(f"{title}\n{body}").upper()
    if "FLEDERMAUS" in normalized or ("BAT" in normalized and "DETECTOR" in normalized):
        return "bat_detector"
    if any(keyword in normalized for keyword in ("KARTE", "MAP", "POLYGON", "GEODATA", "GEO", "GIS")):
        return "map"
    return "generic"


def _draw_glow(draw, cx: int, cy: int, radius: int, color: tuple[int, int, int], alpha: int) -> None:
    for step in range(radius, 0, -1):
        current_alpha = int(alpha * (step / radius) ** 2)
        draw.ellipse((cx - step, cy - step, cx + step, cy + step), fill=(*color, max(0, min(255, current_alpha))))


def _draw_bat_scene(draw, width: int, height: int, title_text: str, body_text: str, title_font, body_font) -> None:
    draw.rectangle((0, 0, width, height), fill=(6, 11, 17, 255))
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(8 + ratio * 18)
        g = int(15 + ratio * 24)
        b = int(24 + ratio * 34)
        draw.line((0, y, width, y), fill=(r, g, b, 255))

    _draw_glow(draw, int(width * 0.28), int(height * 0.26), 180, (94, 149, 255), 110)
    _draw_glow(draw, int(width * 0.78), int(height * 0.18), 200, (99, 215, 191), 92)
    _draw_glow(draw, int(width * 0.58), int(height * 0.48), 260, (255, 194, 92), 100)

    draw.rounded_rectangle((36, 36, width - 36, height - 36), radius=34, outline=(255, 255, 255, 28), width=2)
    draw.rounded_rectangle((64, 64, 360, 138), radius=24, fill=(99, 215, 191, 210))
    draw.text((90, 90), "Hippo AI", fill=(9, 18, 24, 255), font=body_font)

    headline = title_text.strip() or "FLEDERMAUS DETEKTOR"
    draw.text((64, 165), headline.upper(), fill=(243, 247, 252, 255), font=title_font)
    subtitle = "Ultraschall hören. Fledermäuse schützen."
    draw.text((64, 240), subtitle, fill=(211, 226, 240, 255), font=body_font)

    # Left panel with feature steps.
    panel = (64, 300, 505, 640)
    draw.rounded_rectangle(panel, radius=26, fill=(11, 19, 28, 190), outline=(255, 255, 255, 24), width=1)
    steps = [
        "1  Fledermäuse senden Ultraschallrufe aus.",
        "2  Der Detektor nimmt die Signale mit dem Mikrofon auf.",
        "3  Die Signale werden als hörbare Töne oder Spektrogramm dargestellt.",
    ]
    y = 326
    for index, step in enumerate(steps):
        circle_x = 92
        circle_y = y + 14
        draw.ellipse((circle_x - 14, circle_y - 14, circle_x + 14, circle_y + 14), fill=(122, 186, 68, 255))
        draw.text((circle_x - 6, circle_y - 9), str(index + 1), fill=(10, 16, 13, 255), font=body_font)
        wrapped = _wrap_text(draw, step, body_font, 360)
        text_y = y
        for line in wrapped:
            draw.text((124, text_y), line, fill=(233, 240, 248, 255), font=body_font)
            text_y += 26
        y = text_y + 26

    # Central detector device.
    body_box = (530, 190, 860, 620)
    draw.rounded_rectangle(body_box, radius=28, fill=(14, 18, 25, 255), outline=(255, 255, 255, 26), width=2)
    draw.rounded_rectangle((620, 160, 770, 200), radius=12, fill=(31, 42, 56, 255))
    draw.rectangle((692, 96, 698, 190), fill=(76, 84, 96, 255))
    draw.ellipse((674, 82, 716, 124), fill=(30, 36, 44, 255), outline=(255, 255, 255, 40))
    draw.ellipse((689, 101, 701, 113), fill=(99, 215, 191, 255))
    draw.text((596, 232), "BAT DETECTOR", fill=(242, 248, 253, 255), font=body_font)
    draw.text((625, 290), "STATUS", fill=(150, 164, 180, 255), font=body_font)
    draw.ellipse((678, 324, 694, 340), fill=(99, 215, 191, 255))
    draw.rounded_rectangle((585, 360, 805, 520), radius=18, fill=(24, 30, 41, 255), outline=(255, 255, 255, 24), width=1)
    draw.text((610, 548), "ULTRASCHALL DETEKTOR", fill=(211, 222, 233, 255), font=body_font)
    wing_left = [(595, 454), (528, 420), (478, 385), (455, 350), (474, 334), (545, 365), (587, 396), (620, 434)]
    wing_right = [(745, 454), (812, 420), (862, 385), (885, 350), (866, 334), (795, 365), (753, 396), (720, 434)]
    draw.polygon(wing_left, fill=(84, 89, 97, 255))
    draw.polygon(wing_right, fill=(84, 89, 97, 255))
    draw.ellipse((620, 425, 745, 495), fill=(71, 76, 84, 255))
    draw.line((640, 425, 630, 398), fill=(103, 109, 118, 255), width=3)
    draw.line((720, 425, 730, 398), fill=(103, 109, 118, 255), width=3)

    # Right side smartphone with spectrogram.
    phone = (920, 235, 1140, 585)
    draw.rounded_rectangle(phone, radius=30, fill=(8, 11, 15, 255), outline=(255, 255, 255, 26), width=2)
    draw.rounded_rectangle((945, 264, 1115, 540), radius=18, fill=(18, 12, 28, 255))
    for idx in range(0, 13):
        x = 960 + idx * 10
        for y2 in range(300, 524):
            intensity = max(0, 255 - abs((y2 - 410) * 2) - idx * 9)
            if intensity > 40:
                draw.point((x, y2), fill=(255, 70 + idx * 8, 115, intensity))
    draw.text((972, 280), "LIVE - Ultraschall", fill=(122, 215, 115, 255), font=body_font)
    draw.text((972, 555), "Analyse", fill=(191, 201, 213, 255), font=body_font)

    # Sound waves and bat silhouette.
    for wave in range(5):
        start = 815 + wave * 28
        draw.arc((760, 150, 995 + wave * 20, 420), start=220, end=320, fill=(160, 181, 204, 130), width=3)

    bat_center = (1110, 175)
    draw.ellipse((bat_center[0] - 28, bat_center[1] - 18, bat_center[0] + 28, bat_center[1] + 18), fill=(43, 32, 28, 255))
    left_wing = [(bat_center[0] - 20, bat_center[1]), (bat_center[0] - 150, bat_center[1] - 90), (bat_center[0] - 220, bat_center[1] - 20), (bat_center[0] - 150, bat_center[1] + 10)]
    right_wing = [(bat_center[0] + 20, bat_center[1]), (bat_center[0] + 150, bat_center[1] - 90), (bat_center[0] + 220, bat_center[1] - 20), (bat_center[0] + 150, bat_center[1] + 10)]
    draw.polygon(left_wing, fill=(33, 24, 22, 255))
    draw.polygon(right_wing, fill=(33, 24, 22, 255))
    draw.text((978, 612), "Warum ist das wichtig?", fill=(122, 186, 68, 255), font=body_font)
    draw.text((978, 648), "Viele Fledermausarten sind bedroht.", fill=(233, 240, 248, 255), font=body_font)
    draw.text((978, 674), "Mit einem Detektor kannst du sie beobachten und schützen.", fill=(233, 240, 248, 255), font=body_font)

    # Bottom feature strip.
    strip = (64, 666, 1140, 820)
    draw.rounded_rectangle(strip, radius=24, fill=(11, 19, 28, 196), outline=(255, 255, 255, 24), width=1)
    mini_cards = [
        ("20-120 kHz", "Erkennt Ultraschallrufe"),
        ("Spektrogramm", "Live Analyse"),
        ("Speichern", "Aufnahmen sichern"),
        ("Mobil", "Ideal für unterwegs"),
    ]
    card_x = 84
    for label, desc in mini_cards:
        draw.rounded_rectangle((card_x, 690, card_x + 230, 796), radius=18, fill=(18, 27, 39, 230))
        draw.text((card_x + 16, 706), label, fill=(122, 186, 68, 255), font=body_font)
        wrapped = _wrap_text(draw, desc, body_font, 180)
        text_y = 735
        for line in wrapped[:3]:
            draw.text((card_x + 16, text_y), line, fill=(233, 240, 248, 255), font=body_font)
            text_y += 24
        card_x += 250


def build_raster_image_bytes(title: str, body: str, format_name: str) -> bytes:
    if Image is None or ImageDraw is None or ImageFont is None:
        return _build_fallback_png_bytes(title, body)

    width, height = 1400, 900
    img = Image.new("RGBA", (width, height), (10, 16, 22, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    title_text = (title or "Hippo AI").strip()
    body_text = (body or "").strip()
    title_font = _load_font(64, bold=True)
    body_font = _load_font(26, bold=False)

    topic = _topic_key(title_text, body_text)
    if topic == "bat_detector":
        _draw_bat_scene(draw, width, height, title_text, body_text, title_font, body_font)
    else:
        for y in range(height):
            ratio = y / max(1, height - 1)
            r = int(10 + ratio * 16)
            g = int(16 + ratio * 22)
            b = int(22 + ratio * 26)
            draw.line((0, y, width, y), fill=(r, g, b, 255))

        draw.rounded_rectangle((40, 40, width - 40, height - 40), radius=36, fill=(18, 27, 39, 245), outline=(255, 255, 255, 70), width=2)
        draw.rounded_rectangle((70, 70, 400, 140), radius=28, fill=(99, 215, 191, 220))
        draw.text((98, 92), "Hippo AI", fill=(8, 17, 24, 255), font=body_font)

        wrapped_title = _wrap_text(draw, title_text, title_font, 1160)
        y = 170
        for line in wrapped_title[:4]:
            draw.text((96, y), line, fill=(237, 244, 251, 255), font=title_font)
            y += 74

        if body_text:
            y += 12
            wrapped_body = _wrap_text(draw, body_text, body_font, 1210)
            for line in wrapped_body[:18]:
                draw.text((96, y), line, fill=(201, 215, 230, 255), font=body_font)
                y += 34

        # Add a small abstract visual cluster so the image is not text-only.
        draw.ellipse((900, 180, 1180, 460), fill=(44, 66, 92, 255), outline=(99, 215, 191, 120), width=3)
        draw.ellipse((965, 245, 1115, 395), fill=(99, 215, 191, 180))
        for idx in range(6):
            angle = math.radians(40 + idx * 18)
            x1 = 1040 + int(math.cos(angle) * 160)
            y1 = 320 + int(math.sin(angle) * 160)
            draw.line((1040, 320, x1, y1), fill=(154, 178, 255, 180), width=5)

        footer = f"Generated by Hippo AI · {format_name.upper()}"
        draw.text((96, height - 72), footer, fill=(99, 215, 191, 255), font=body_font)

    buffer = BytesIO()
    save_format = "JPEG" if format_name.lower() in {"jpg", "jpeg"} else "PNG"
    if save_format == "JPEG":
        img = img.convert("RGB")
        img.save(buffer, format=save_format, quality=92, optimize=True)
    else:
        img.save(buffer, format=save_format, optimize=True)
    return buffer.getvalue()


def build_generated_file_bytes(filename: str, content: str) -> tuple[bytes, str]:
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    base_title = Path(safe_name).stem.replace("_", " ").strip() or "Hippo AI"
    body = content.strip()

    if ext == ".docx":
        return build_docx_bytes(base_title, body), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".pdf":
        return build_simple_pdf_bytes(base_title, body), "application/pdf"
    if ext == ".rtf":
        return build_rtf_bytes(base_title, body), "application/rtf"
    if ext == ".svg":
        return build_svg_bytes(base_title, body), "image/svg+xml"
    if ext == ".png":
        return build_raster_image_bytes(base_title, body, "png"), "image/png"
    if ext in {".jpg", ".jpeg"}:
        if Image is None or ImageDraw is None or ImageFont is None:
            return _build_fallback_png_bytes(base_title, body), "image/png"
        return build_raster_image_bytes(base_title, body, "jpeg"), "image/jpeg"
    guessed_type, _ = mimetypes.guess_type(safe_name)
    return body.encode("utf-8"), guessed_type or "text/plain; charset=utf-8"


def build_generated_file_bytes_with_fallback(filename: str, content: str) -> tuple[bytes, str, str]:
    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    try:
        data, mime_type = build_generated_file_bytes(safe_name, content)
        if ext in {".jpg", ".jpeg"} and mime_type == "image/png":
            return data, mime_type, f"{Path(safe_name).stem}.png"
        return data, mime_type, safe_name
    except RuntimeError as exc:
        if ext not in {".png", ".jpg", ".jpeg"}:
            raise
        base_title = Path(safe_name).stem.replace("_", " ").strip() or "Hippo AI"
        fallback_name = f"{Path(safe_name).stem}.png"
        return _build_fallback_png_bytes(base_title, content or ""), "image/png", fallback_name


def save_generated_file(folder: str, filename: str, content: str) -> str:
    safe_name = Path(filename).name
    data, _, out_name = build_generated_file_bytes_with_fallback(safe_name, content)
    target = Path(folder) / out_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    return str(target)
