from __future__ import annotations

from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .models import AnalysisResult, SpeciesAnalysis
from .reporter import render_report


def export_report(result: AnalysisResult, output_path: str | Path) -> Path:
    """Exportiert den Bericht als TXT oder DOCX."""

    path = Path(output_path)
    suffix = path.suffix.lower()

    if suffix == ".docx":
        _write_docx(path, result, render_report(result))
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
