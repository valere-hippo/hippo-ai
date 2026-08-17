from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .models import AnalysisResult, SpeciesAnalysis
from .reporter import render_report


def export_report(result: AnalysisResult, output_path: str | Path) -> Path:
    """Exportiert den Bericht als TXT, DOCX oder PDF."""

    path = Path(output_path)
    suffix = path.suffix.lower()

    if suffix == ".docx":
        _write_docx(path, result, render_report(result))
    elif suffix == ".pdf":
        _write_pdf(path, render_report(result))
    else:
        path.write_text(render_report(result), encoding="utf-8")

    return path


def _write_docx(path: Path, result: AnalysisResult, report_text: str) -> None:
    paragraphs = report_text.rstrip("\n").split("\n")

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("docProps/core.xml", _core_props_xml())
        archive.writestr("docProps/app.xml", _app_props_xml())
        archive.writestr("word/styles.xml", _styles_xml())
        archive.writestr("word/numbering.xml", _numbering_xml())
        archive.writestr("word/header1.xml", _header_xml())
        archive.writestr("word/footer1.xml", _footer_xml())
        archive.writestr("word/_rels/document.xml.rels", _document_rels_xml())
        archive.writestr("word/document.xml", _document_xml(result, paragraphs))


def _write_pdf(path: Path, report_text: str) -> None:
    pages = _build_pdf_pages(report_text)
    pdf_bytes = _build_pdf_document(pages)
    path.write_bytes(pdf_bytes)


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
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


def _document_xml(result: AnalysisResult, paragraphs: Iterable[str]) -> str:
    body_parts: list[str] = []
    skip_overview_bullets = False
    toc_inserted = False
    skip_toc_bullets = False
    for index, line in enumerate(paragraphs):
        if not line.strip():
            if skip_overview_bullets:
                skip_overview_bullets = False
            if skip_toc_bullets:
                skip_toc_bullets = False
            body_parts.append("<w:p><w:pPr><w:spacing w:after=\"120\"/></w:pPr></w:p>")
            continue
        if line == "## Inhaltsverzeichnis":
            body_parts.append(_styled_paragraph("Heading1", "Inhaltsverzeichnis"))
            body_parts.append(_toc_field_paragraph())
            toc_inserted = True
            skip_toc_bullets = True
            continue
        if skip_toc_bullets and line.startswith("- "):
            continue
        if skip_toc_bullets:
            skip_toc_bullets = False
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
        "<w:headerReference w:type=\"default\" r:id=\"rId1\"/>"
        "<w:footerReference w:type=\"default\" r:id=\"rId2\"/>"
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


def _toc_field_paragraph() -> str:
    return (
        "<w:p>"
        "<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r>"
        "<w:r><w:instrText xml:space=\"preserve\"> TOC \\o \"1-1\" \\h \\z \\u </w:instrText></w:r>"
        "<w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>"
        "<w:r><w:t xml:space=\"preserve\">In Word aktualisieren, um das Inhaltsverzeichnis zu erzeugen.</w:t></w:r>"
        "<w:r><w:fldChar w:fldCharType=\"end\"/></w:r>"
        "</w:p>"
    )


def _build_pdf_pages(report_text: str) -> list[list[str]]:
    sections = _parse_report_sections(report_text)
    pages: list[list[str]] = []
    pages.append(_pdf_cover_page(sections))
    if sections["overview_table"]:
        pages.append(_pdf_overview_page(sections))
    for block in sections["species_blocks"]:
        pages.append(_pdf_species_page(block))
    if sections["warnings"]:
        pages.append(_pdf_list_page("Warnungen", sections["warnings"]))
    if sections["validation"]:
        pages.append(_pdf_list_page("Validierung", sections["validation"]))
    return pages or [["Tier-KI Auswertung"]]


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


def _pdf_cover_page(sections: dict[str, object]) -> list[str]:
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
    return _wrap_pdf_lines(lines)


def _pdf_overview_page(sections: dict[str, object]) -> list[str]:
    lines = ["Übersicht", ""]
    lines.extend(str(line) for line in sections["overview_table"])
    return _wrap_pdf_lines(lines)


def _pdf_species_page(block: dict[str, list[str]]) -> list[str]:
    lines = [block["name"][0], ""]
    lines.extend(block["lines"])
    return _wrap_pdf_lines(lines)


def _pdf_list_page(title: str, items: list[str]) -> list[str]:
    lines = [title, ""]
    lines.extend(items)
    return _wrap_pdf_lines(lines)


def _wrap_pdf_lines(lines: list[str]) -> list[str]:
    max_chars_per_line = 92
    wrapped_lines: list[str] = []
    for raw_line in lines:
        if not raw_line.strip():
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(textwrap.wrap(raw_line, width=max_chars_per_line) or [""])
    return wrapped_lines


def _build_pdf_document(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add_object(content: str | bytes) -> int:
        if isinstance(content, str):
            content_bytes = content.encode("latin-1")
        else:
            content_bytes = content
        objects.append(content_bytes)
        return len(objects)

    font_obj = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    content_obj_ids: list[int] = []
    page_obj_ids: list[int] = []
    for page_lines in pages:
        content_stream = _pdf_page_stream(page_lines)
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
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
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


def _pdf_page_stream(page_lines: list[str]) -> bytes:
    y = 800
    lines = [
        "BT",
        "/F1 11 Tf",
        "72 800 Td",
        "13 TL",
    ]
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
    stream = "\n".join(lines).encode("latin-1")
    return f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"


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
                species_result.species,
                species_result.taxon_group,
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
