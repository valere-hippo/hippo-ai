from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .models import AnalysisResult, SpeciesAnalysis
from .reporter import render_report


def export_report(
    result: AnalysisResult,
    output_path: str | Path,
    *,
    docx_template_dir: str | Path | None = None,
) -> Path:
    """Exportiert den Bericht als TXT, DOCX oder PDF."""

    path = Path(output_path)
    suffix = path.suffix.lower()

    if suffix == ".docx":
        _write_docx(path, result, render_report(result), template_dir=docx_template_dir)
    elif suffix == ".pdf":
        _write_pdf(path, render_report(result))
    else:
        path.write_text(render_report(result), encoding="utf-8")

    return path


def _write_docx(
    path: Path,
    result: AnalysisResult,
    report_text: str,
    *,
    template_dir: str | Path | None = None,
) -> None:
    paragraphs = report_text.rstrip("\n").split("\n")
    template_parts = _load_docx_template_parts(Path(template_dir)) if template_dir else {}
    header_rel_id, footer_rel_id = _docx_relationship_ids(template_parts.get("document_rels_xml"))
    logo_rel_id = "rIdLogo"
    document_rels_xml = _inject_logo_relationship(template_parts.get("document_rels_xml"), logo_rel_id)

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _inject_logo_content_type(template_parts.get("content_types_xml")))
        archive.writestr("_rels/.rels", template_parts.get("root_rels_xml", _root_rels_xml()))
        archive.writestr("docProps/core.xml", template_parts.get("core_props_xml", _core_props_xml()))
        archive.writestr("docProps/app.xml", template_parts.get("app_props_xml", _app_props_xml()))
        archive.writestr("word/styles.xml", template_parts.get("styles_xml", _styles_xml()))
        archive.writestr("word/numbering.xml", template_parts.get("numbering_xml", _numbering_xml()))
        archive.writestr("word/header1.xml", template_parts.get("header_xml", _header_xml()))
        archive.writestr("word/footer1.xml", template_parts.get("footer_xml", _footer_xml()))
        archive.writestr("word/_rels/document.xml.rels", document_rels_xml)
        archive.writestr("word/media/logo.svg", _logo_svg_bytes())
        archive.writestr("word/document.xml", _document_xml(result, paragraphs, header_rel_id, footer_rel_id, logo_rel_id))


def _write_pdf(path: Path, report_text: str) -> None:
    pages = _build_pdf_pages(report_text)
    pdf_bytes = _build_pdf_document(pages)
    path.write_bytes(pdf_bytes)


def _load_docx_template_parts(template_dir: Path) -> dict[str, str]:
    parts: dict[str, str] = {}
    mapping = {
        "content_types_xml": "[Content_Types].xml",
        "root_rels_xml": "_rels/.rels",
        "core_props_xml": "docProps/core.xml",
        "app_props_xml": "docProps/app.xml",
        "styles_xml": "word/styles.xml",
        "numbering_xml": "word/numbering.xml",
        "header_xml": "word/header1.xml",
        "footer_xml": "word/footer1.xml",
        "document_rels_xml": "word/_rels/document.xml.rels",
    }
    for key, relative_path in mapping.items():
        candidate = template_dir / relative_path
        if candidate.exists():
            parts[key] = candidate.read_text(encoding="utf-8")
    return parts


def _logo_svg_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "logo.svg"


def _logo_svg_bytes() -> bytes:
    return _logo_svg_path().read_bytes()


def _inject_logo_content_type(content_types_xml: str | None) -> str:
    base = content_types_xml or _content_types_xml()
    if "image/svg+xml" in base:
        return base
    closing = "</Types>"
    if closing not in base:
        return _content_types_xml()
    return base.replace(
        closing,
        '  <Default Extension="svg" ContentType="image/svg+xml"/>\n</Types>',
    )


def _inject_logo_relationship(document_rels_xml: str | None, logo_rel_id: str) -> str:
    base = document_rels_xml or _document_rels_xml()
    if f'Id="{logo_rel_id}"' in base:
        return base
    closing = "</Relationships>"
    if closing not in base:
        return _document_rels_xml()
    logo_rel = (
        f'  <Relationship Id="{logo_rel_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/logo.svg"/>\n'
    )
    return base.replace(closing, logo_rel + "</Relationships>")


def _docx_relationship_ids(document_rels_xml: str | None) -> tuple[str, str]:
    if not document_rels_xml:
        return "rId1", "rId2"
    header_match = re.search(r'Type="[^"]*/header"[^>]*Id="([^"]+)"', document_rels_xml)
    footer_match = re.search(r'Type="[^"]*/footer"[^>]*Id="([^"]+)"', document_rels_xml)
    header_rel_id = header_match.group(1) if header_match else "rId1"
    footer_rel_id = footer_match.group(1) if footer_match else "rId2"
    return header_rel_id, footer_rel_id


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="svg" ContentType="image/svg+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


def _root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def _document_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>
"""


def _numbering_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>
"""


def _header_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:pPr><w:jc w:val="center"/></w:pPr>
    <w:r><w:rPr><w:b/><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">Tier-KI Auswertung</w:t></w:r>
  </w:p>
  <w:p>
    <w:pPr><w:jc w:val="center"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">Geospatiale Fachauswertung für Artenschutzberichte</w:t></w:r>
  </w:p>
</w:hdr>
"""


def _footer_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p>
    <w:pPr><w:jc w:val="center"/></w:pPr>
    <w:r><w:t xml:space="preserve">tier-ai</w:t></w:r>
    <w:r><w:t xml:space="preserve"> | </w:t></w:r>
    <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:t>1</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r>
  </w:p>
</w:ftr>
"""


def _core_props_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Tier-KI Auswertung</dc:title>
  <dc:creator>tier-ai</dc:creator>
  <cp:lastModifiedBy>tier-ai</cp:lastModifiedBy>
</cp:coreProperties>
"""


def _app_props_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>tier-ai</Application>
</Properties>
"""


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:rPr>
      <w:rFonts w:ascii="Aptos" w:hAnsi="Aptos"/>
      <w:sz w:val="22"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:basedOn w:val="Normal"/>
    <w:next w:val="Normal"/>
    <w:qFormat/>
    <w:pPr>
      <w:jc w:val="center"/>
      <w:spacing w:after="180"/>
    </w:pPr>
    <w:rPr>
      <w:b/>
      <w:sz w:val="34"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle">
    <w:name w:val="Subtitle"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr>
      <w:jc w:val="center"/>
      <w:spacing w:after="240"/>
    </w:pPr>
    <w:rPr>
      <w:i/>
      <w:sz w:val="20"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:pPr>
      <w:spacing w:before="240" w:after="120"/>
    </w:pPr>
    <w:rPr>
      <w:b/>
      <w:sz w:val="28"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ListBullet">
    <w:name w:val="List Bullet"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr>
      <w:ind w:left="720" w:hanging="360"/>
      <w:spacing w:after="60"/>
    </w:pPr>
  </w:style>
</w:styles>
"""


def _document_xml(
    result: AnalysisResult,
    paragraphs: Iterable[str],
    header_rel_id: str = "rId1",
    footer_rel_id: str = "rId2",
    logo_rel_id: str = "rIdLogo",
) -> str:
    body_parts: list[str] = [_logo_paragraph_xml(logo_rel_id)]
    skip_overview_bullets = False
    for index, line in enumerate(paragraphs):
        if not line.strip():
            if skip_overview_bullets:
                skip_overview_bullets = False
            body_parts.append("<w:p><w:pPr><w:spacing w:after=\"120\"/></w:pPr></w:p>")
            continue
        if line == "## Übersicht":
            body_parts.append(_styled_paragraph("Heading1", "Übersicht"))
            body_parts.append(_species_overview_table_xml(result.species_results))
            skip_overview_bullets = True
            continue
        if skip_overview_bullets and line.startswith("- "):
            continue
        if skip_overview_bullets:
            skip_overview_bullets = False
        body_parts.append(_paragraph_xml(line, index))

    body_parts.append(
        "<w:sectPr>"
        f"<w:headerReference w:type=\"default\" r:id=\"{header_rel_id}\"/>"
        f"<w:footerReference w:type=\"default\" r:id=\"{footer_rel_id}\"/>"
        "<w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/>"
        "</w:sectPr>"
    )
    body = "".join(body_parts)
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
 xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
 xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
 xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
 xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 mc:Ignorable="w14 wp14">
  <w:body>%s</w:body>
</w:document>
""" % body


def _logo_paragraph_xml(logo_rel_id: str) -> str:
    return (
        '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr>'
        '<w:r><w:drawing>'
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="1440000" cy="1440000"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:docPr id="1" name="Tier-KI Logo"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic>'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic>'
        '<pic:nvPicPr>'
        '<pic:cNvPr id="0" name="logo.svg"/>'
        '<pic:cNvPicPr/>'
        '</pic:nvPicPr>'
        '<pic:blipFill>'
        f'<a:blip r:embed="{logo_rel_id}"/>'
        '<a:stretch><a:fillRect/></a:stretch>'
        '</pic:blipFill>'
        '<pic:spPr>'
        '<a:xfrm><a:off x="0" y="0"/><a:ext cx="1440000" cy="1440000"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        '</pic:spPr>'
        '</pic:pic>'
        '</a:graphicData>'
        '</a:graphic>'
        '</wp:inline>'
        '</w:drawing></w:r></w:p>'
    )


def _paragraph_xml(line: str, index: int) -> str:
    if index == 0:
        return _styled_paragraph("Title", line)
    if index == 1 and line.startswith("Quelle:"):
        return _styled_paragraph("Subtitle", line)
    if line.startswith("## "):
        return _styled_paragraph("Heading1", line[3:])
    if line.startswith("- "):
        return _styled_paragraph("ListBullet", f"• {line[2:]}")
    return _styled_paragraph("Normal", line)


def _styled_paragraph(style_id: str, text: str) -> str:
    return (
        "<w:p><w:pPr><w:pStyle w:val=\"%s\"/></w:pPr>"
        "<w:r><w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>"
        % (style_id, escape(text))
    )


def _build_pdf_pages(report_text: str) -> list[dict[str, object]]:
    sections = _parse_report_sections(report_text)
    pages: list[dict[str, object]] = []
    pages.append(_pdf_cover_page(sections))
    if sections["overview_table"]:
        pages.append(_pdf_overview_page(sections))
    for block in sections["species_blocks"]:
        pages.append(_pdf_species_page(block))
    if sections["warnings"]:
        pages.append(_pdf_list_page("Warnungen", sections["warnings"]))
    if sections["validation"]:
        pages.append(_pdf_list_page("Validierung", sections["validation"]))
    return pages or [{"lines": ["Tier-KI Auswertung"], "logo": False}]


def _parse_report_sections(report_text: str) -> dict[str, object]:
    lines = [line.rstrip() for line in report_text.rstrip("\n").split("\n")]
    sections: dict[str, object] = {
        "title": lines[0] if lines else "Tier-KI Auswertung",
        "source": lines[1] if len(lines) > 1 else "",
        "summary": "",
        "conclusion": "",
        "overview_table": [],
        "species_blocks": [],
        "warnings": [],
        "validation": [],
    }

    current_section: str | None = None
    current_species: dict[str, list[str]] | None = None
    pending_lines: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_lines, current_section
        if current_section == "summary":
            sections["summary"] = " ".join(line.strip() for line in pending_lines if line.strip())
        elif current_section == "conclusion":
            sections["conclusion"] = " ".join(line.strip() for line in pending_lines if line.strip())
        elif current_section == "warnings":
            sections["warnings"].extend(line for line in pending_lines if line.strip())  # type: ignore[union-attr]
        elif current_section == "validation":
            sections["validation"].extend(line for line in pending_lines if line.strip())  # type: ignore[union-attr]
        pending_lines = []
        current_section = None

    def flush_species() -> None:
        nonlocal current_species
        if current_species is not None:
            sections["species_blocks"].append(current_species)  # type: ignore[union-attr]
            current_species = None

    for line in lines[2:]:
        if line.startswith("## "):
            flush_pending()
            heading = line[3:]
            if current_species is not None and heading != current_species["name"][0]:
                flush_species()

            if heading == "Zusammenfassung":
                current_section = "summary"
            elif heading == "Schlussbewertung":
                current_section = "conclusion"
            elif heading == "Übersicht":
                current_section = "overview"
            elif heading == "Warnungen":
                current_section = "warnings"
            elif heading == "Validierung":
                current_section = "validation"
            else:
                current_species = {"name": [heading], "lines": []}
                current_section = "species"
            continue

        if current_section == "overview":
            sections["overview_table"].append(line)  # type: ignore[union-attr]
        elif current_section == "species" and current_species is not None:
            current_species["lines"].append(line)
        else:
            pending_lines.append(line)

    flush_pending()
    flush_species()
    return sections


def _pdf_cover_page(sections: dict[str, object]) -> dict[str, object]:
    lines = [
        str(sections["title"]),
        "",
        str(sections["source"]),
        "",
        "Zusammenfassung",
        str(sections["summary"]),
        "",
        "Schlussbewertung",
        str(sections["conclusion"]),
    ]
    return {"lines": _wrap_pdf_lines(lines), "logo": True}


def _pdf_overview_page(sections: dict[str, object]) -> dict[str, object]:
    lines = ["Übersicht", ""]
    lines.extend(str(line) for line in sections["overview_table"])
    return {"lines": _wrap_pdf_lines(lines), "logo": False}


def _pdf_species_page(block: dict[str, list[str]]) -> dict[str, object]:
    lines = [block["name"][0], ""]
    lines.extend(block["lines"])
    return {"lines": _wrap_pdf_lines(lines), "logo": False}


def _pdf_list_page(title: str, items: list[str]) -> dict[str, object]:
    lines = [title, ""]
    lines.extend(items)
    return {"lines": _wrap_pdf_lines(lines), "logo": False}


def _wrap_pdf_lines(lines: list[str]) -> list[str]:
    max_chars_per_line = 92
    wrapped_lines: list[str] = []
    for raw_line in lines:
        if not raw_line.strip():
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(raw_line, width=max_chars_per_line) or [""])
    return wrapped_lines


def _build_pdf_document(pages: list[dict[str, object]]) -> bytes:
    objects: list[bytes] = []

    def add_object(content: str | bytes) -> int:
        if isinstance(content, str):
            content_bytes = content.encode("latin-1")
        else:
            content_bytes = content
        objects.append(content_bytes)
        return len(objects)

    font_obj = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    bold_font_obj = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    content_obj_ids: list[int] = []
    page_obj_ids: list[int] = []
    for page in pages:
        content_stream = _pdf_page_stream(page)
        content_obj_ids.append(add_object(content_stream))
        page_obj_ids.append(len(objects) + 1)
        objects.append(b"")

    pages_obj_id = len(objects) + 1
    objects.append(b"")
    catalog_obj_id = len(objects) + 1
    objects.append(b"")
    info_obj_id = add_object(
        "<< /Producer (tier-ai) /Title (Tier-KI Auswertung) /Creator (tier-ai) >>"
    )

    page_object_templates: list[bytes] = []
    for content_obj_id in content_obj_ids:
        page_object_templates.append(
            (
                f"<< /Type /Page /Parent {pages_obj_id} 0 R "
                f"/MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_obj} 0 R /F2 {bold_font_obj} 0 R >> >> "
                f"/Contents {content_obj_id} 0 R >>"
            ).encode("latin-1")
        )

    kids = " ".join(f"{page_obj_id} 0 R" for page_obj_id in page_obj_ids)
    pages_object = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_obj_ids)} >>".encode("latin-1")
    catalog_object = f"<< /Type /Catalog /Pages {pages_obj_id} 0 R >>".encode("latin-1")

    for index, page_object in enumerate(page_object_templates):
        objects[page_obj_ids[index] - 1] = page_object
    objects[pages_obj_id - 1] = pages_object
    objects[catalog_obj_id - 1] = catalog_object

    return _serialize_pdf(objects, catalog_obj_id, info_obj_id)


def _pdf_page_stream(page: dict[str, object]) -> bytes:
    page_lines = [str(line) for line in page.get("lines", [])]
    include_logo = bool(page.get("logo"))
    lines = [
        "q",
    ]
    if include_logo:
        lines.extend(_pdf_logo_commands())
    lines.extend([
        "BT",
        "/F1 11 Tf",
        f"72 {560 if include_logo else 800} Td",
        "13 TL",
    ])
    first_line = True
    for raw_line in page_lines:
        escaped = _pdf_escape_text(raw_line)
        if first_line:
            lines.append(f"({escaped}) Tj")
            first_line = False
        elif raw_line:
            lines.append(f"T* ({escaped}) Tj")
        else:
            lines.append("T* () Tj")
    lines.append("ET")
    lines.append("Q")
    stream = "\n".join(lines).encode("latin-1")
    return f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"


def _pdf_logo_commands() -> list[str]:
    svg_root = ET.fromstring(_logo_svg_path().read_text(encoding="utf-8"))
    commands: list[str] = []
    x = 188
    y_top = 760
    scale = 1.45
    commands.append(f"1 0 0 -1 {x} {y_top} cm")
    commands.append(f"{scale} 0 0 {scale} 0 0 cm")
    for element in svg_root:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "defs":
            continue
        if tag == "rect":
            commands.extend(_pdf_rect_commands(element.attrib))
        elif tag == "path":
            commands.extend(_pdf_path_commands(element.attrib))
        elif tag == "circle":
            commands.extend(_pdf_circle_commands(element.attrib))
    commands.extend(
        [
            "0.48 0.07 0.19 rg",
            "0.48 0.07 0.19 RG",
            "BT",
            "/F2 18 Tf",
            "0 -26 Td",
            "(hipposideros) Tj",
            "T* /F2 8 Tf",
            "(landschaftsökologie) Tj",
            "T* /F2 8 Tf",
            "(Ökosystemmanagement) Tj",
            "ET",
        ]
    )
    return commands


def _pdf_rect_commands(attributes: dict[str, str]) -> list[str]:
    x = float(attributes.get("x", "0"))
    y = float(attributes.get("y", "0"))
    width = float(attributes.get("width", "0"))
    height = float(attributes.get("height", "0"))
    rx = float(attributes.get("rx", "0"))
    commands = [
        "0.06 0.03 0.04 rg",
        "0.25 0.03 0.09 RG",
        "2 w",
    ]
    if rx > 0:
        commands.extend(_pdf_round_rect_path(x, y, width, height, rx, rx))
    else:
        commands.extend([f"{x} {y} {width} {height} re"])
    commands.append("B")
    return commands


def _pdf_circle_commands(attributes: dict[str, str]) -> list[str]:
    cx = float(attributes.get("cx", "0"))
    cy = float(attributes.get("cy", "0"))
    radius = float(attributes.get("r", "0"))
    fill = attributes.get("fill", "#EAF5EE")
    if fill == "#10070B":
        commands = ["0.06 0.03 0.04 rg"]
    else:
        commands = ["0.91 0.85 0.86 rg"]
    commands.extend(_pdf_ellipse_path(cx - radius, cy - radius, radius * 2, radius * 2))
    commands.append("f")
    return commands


def _pdf_path_commands(attributes: dict[str, str]) -> list[str]:
    d = attributes.get("d", "")
    fill = attributes.get("fill")
    stroke = attributes.get("stroke")
    stroke_width = float(attributes.get("stroke-width", "1"))
    commands: list[str] = []
    if fill and fill != "none":
        if "#E8D9DB" in fill:
            commands.append("0.91 0.85 0.86 rg")
        else:
            commands.append("0.66 0.12 0.25 rg")
    if stroke and stroke != "none":
        if "#E8D9DB" in stroke:
            commands.append("0.91 0.85 0.86 RG")
        else:
            commands.append("0.48 0.07 0.19 RG")
        commands.append(f"{stroke_width} w")
    commands.extend(_pdf_svg_path_to_ops(d))
    if fill and fill != "none" and stroke and stroke != "none":
        commands.append("B")
    elif fill and fill != "none":
        commands.append("f")
    elif stroke and stroke != "none":
        commands.append("S")
    return commands


def _pdf_svg_path_to_ops(path_data: str) -> list[str]:
    tokens = re.findall(r"[MmCcZz]|-?\d+(?:\.\d+)?", path_data)
    commands: list[str] = []
    index = 0
    current_command: str | None = None
    while index < len(tokens):
        token = tokens[index]
        if token in {"M", "m", "C", "c", "Z", "z"}:
            current_command = token
            index += 1
            if token in {"Z", "z"}:
                commands.append("h")
                current_command = None
            continue
        if current_command == "M":
            x = tokens[index]
            y = tokens[index + 1]
            commands.append(f"{x} {y} m")
            index += 2
            current_command = "C"
        elif current_command == "C":
            x1, y1, x2, y2, x3, y3 = tokens[index:index + 6]
            commands.append(f"{x1} {y1} {x2} {y2} {x3} {y3} c")
            index += 6
        else:
            index += 1
    return commands


def _pdf_round_rect_path(x: float, y: float, width: float, height: float, rx: float, ry: float) -> list[str]:
    kappa = 0.5522847498
    ox = rx * kappa
    oy = ry * kappa
    x1 = x + width
    y1 = y + height
    return [
        f"{x + rx} {y} m",
        f"{x1 - rx} {y} l",
        f"{x1 - rx + ox} {y} {x1} {y + ry - oy} {x1} {y + ry} c",
        f"{x1} {y1 - ry} l",
        f"{x1} {y1 - ry + oy} {x1 - rx + ox} {y1} {x1 - rx} {y1} c",
        f"{x + rx} {y1} l",
        f"{x + rx - ox} {y1} {x} {y1 - ry + oy} {x} {y1 - ry} c",
        f"{x} {y + ry} l",
        f"{x} {y + ry - oy} {x + rx - ox} {y} {x + rx} {y} c",
        "h",
    ]


def _pdf_ellipse_path(x: float, y: float, width: float, height: float) -> list[str]:
    kappa = 0.5522847498
    ox = (width / 2.0) * kappa
    oy = (height / 2.0) * kappa
    xm = x + width / 2.0
    ym = y + height / 2.0
    return [
        f"{xm} {y} m",
        f"{xm + ox} {y} {x + width} {ym - oy} {x + width} {ym} c",
        f"{x + width} {ym + oy} {xm + ox} {y + height} {xm} {y + height} c",
        f"{xm - ox} {y + height} {x} {ym + oy} {x} {ym} c",
        f"{x} {ym - oy} {xm - ox} {y} {xm} {y} c",
        "h",
    ]


def _serialize_pdf(objects: list[bytes], catalog_obj_id: int, info_obj_id: int) -> bytes:
    output = bytearray()
    output.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    offsets: list[int] = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("latin-1"))
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    output.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root {catalog_obj_id} 0 R /Info {info_obj_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")
    )
    return bytes(output)


def _pdf_escape_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _species_overview_table_xml(species_results: list[SpeciesAnalysis]) -> str:
    widths = [1900, 900, 950, 900, 1750, 1500, 2000, 1750]
    headers = ["Art", "Gruppe", "Nachweise", "Cluster", "Brut", "Transit", "Empfehlung", "Priorität"]
    rows = [
        headers,
        *[
            [
                species_result.display_name or species_result.species,
                _display_group_name(species_result.taxon_group),
                str(species_result.total_observations),
                str(len(species_result.clusters)),
                species_result.reproduction_assessment,
                species_result.transit_assessment,
                species_result.recommendation,
                species_result.priority,
            ]
            for species_result in species_results
        ],
    ]

    tbl_parts = [
        "<w:tbl>",
        (
            "<w:tblPr>"
            "<w:tblW w:w=\"9000\" w:type=\"dxa\"/>"
            "<w:tblLayout w:type=\"fixed\"/>"
            "<w:tblBorders>"
            "<w:top w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"A6A6A6\"/>"
            "<w:left w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"A6A6A6\"/>"
            "<w:bottom w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"A6A6A6\"/>"
            "<w:right w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"A6A6A6\"/>"
            "<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"A6A6A6\"/>"
            "<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"A6A6A6\"/>"
            "</w:tblBorders>"
            "</w:tblPr>"
        ),
        "<w:tblGrid>"
        + "".join(f"<w:gridCol w:w=\"{width}\"/>" for width in widths)
        + "</w:tblGrid>",
    ]
    for row_index, row in enumerate(rows):
        tbl_parts.append("<w:tr>")
        for col_index, cell in enumerate(row):
            tbl_parts.append(_table_cell_xml(cell, widths[col_index], header=row_index == 0))
        tbl_parts.append("</w:tr>")
    tbl_parts.append("</w:tbl>")
    return "".join(tbl_parts)


def _table_cell_xml(text: str, width: int, *, header: bool = False) -> str:
    bold = "<w:b/>" if header else ""
    shading = "<w:shd w:fill=\"D9E2F3\"/>" if header else ""
    return (
        "<w:tc>"
        "<w:tcPr>"
        f"<w:tcW w:w=\"{width}\" w:type=\"dxa\"/>"
        f"{shading}"
        "</w:tcPr>"
        "<w:p>"
        "<w:pPr><w:jc w:val=\"left\"/></w:pPr>"
        f"<w:r><w:rPr>{bold}</w:rPr><w:t xml:space=\"preserve\">{escape(text)}</w:t></w:r>"
        "</w:p>"
        "</w:tc>"
    )


def _display_group_name(group: str) -> str:
    normalized = group.strip().casefold()
    if normalized == "unknown":
        return "unbestimmt"
    if normalized == "bat":
        return "Fledermäuse"
    if normalized == "bird":
        return "Vögel"
    return group
