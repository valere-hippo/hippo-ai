from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import re
import html
import mimetypes
import textwrap
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
    def make_line(text: str, font: str, size: int, x: int, y: int) -> str:
        return f"BT /{font} {size} Tf 1 0 0 1 {x} {y} Tm ({_pdf_escape(text)}) Tj ET"

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
    current_page: list[str] = []
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
    current_page.append("BT 0.10 0.49 0.44 rg 72 708 445 2 re f ET")
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
            current_page.append(f"BT /Helvetica 10 Tf 1 0 0 1 72 {y} Tm (____________________________________________) Tj ET")
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
        content = "\n".join(page_lines).encode("utf-8")
        page_obj = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> /Contents {content_obj_num} 0 R >>"
        ).encode("utf-8")
        objects.append(page_obj)
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode("utf-8")
            + content
            + b"\nendstream"
        )

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
        return build_raster_image_bytes(base_title, body, "jpeg"), "image/jpeg"
    guessed_type, _ = mimetypes.guess_type(safe_name)
    return body.encode("utf-8"), guessed_type or "text/plain; charset=utf-8"


def save_generated_file(folder: str, filename: str, content: str) -> str:
    safe_name = Path(filename).name
    data, _ = build_generated_file_bytes(safe_name, content)
    target = Path(folder) / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    return str(target)
