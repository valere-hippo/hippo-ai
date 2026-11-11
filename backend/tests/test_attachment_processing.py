from __future__ import annotations

import base64
import struct
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from app.services.attachment_processing import _extract_geo_bundle_context, extract_attachment_text


def _make_docx_bytes(text: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
            </Types>
            """,
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
            </Relationships>
            """,
        )
        archive.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        )
    return buffer.getvalue()


def test_extract_attachment_text_returns_ocr_text_first():
    attachment = SimpleNamespace(
        filename="shot.png",
        mime_type="image/png",
        data_url="data:image/png;base64," + base64.b64encode(b"image-bytes").decode("ascii"),
        ocr_text="Hallo Welt",
        raw_base64=None,
    )

    assert extract_attachment_text(attachment) == "Hallo Welt"


def test_extract_attachment_text_reads_docx():
    payload = base64.b64encode(_make_docx_bytes("Dokumentinhalt")).decode("ascii")
    attachment = SimpleNamespace(
        filename="note.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data_url=None,
        raw_base64=payload,
        ocr_text=None,
    )

    assert "Dokumentinhalt" in extract_attachment_text(attachment)


def _make_xlsx_bytes() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
              <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
              <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
            </Types>
            """,
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
            </Relationships>
            """,
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets>
                <sheet name="Tabelle1" sheetId="1" r:id="rId1"/>
              </sheets>
            </workbook>
            """,
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
              <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
            </Relationships>
            """,
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="4" uniqueCount="4">
              <si><t>Projekt</t></si>
              <si><t>Status</t></si>
              <si><t>Qualistack</t></si>
              <si><t>Bestanden</t></si>
            </sst>
            """,
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
                <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c></row>
              </sheetData>
            </worksheet>
            """,
        )
    return buffer.getvalue()


def test_extract_attachment_text_reads_xlsx():
    attachment = SimpleNamespace(
        filename="qualistack.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        data_url=None,
        raw_base64=base64.b64encode(_make_xlsx_bytes()).decode("ascii"),
        ocr_text=None,
    )

    text = extract_attachment_text(attachment)
    assert "Tabelle1" in text
    assert "Projekt" in text or "Qualistack" in text
    assert "Bestanden" in text


def test_extract_attachment_text_reads_plain_text():
    attachment = SimpleNamespace(
        filename="readme.txt",
        mime_type="text/plain",
        data_url=None,
        raw_base64=base64.b64encode("Plain text".encode("utf-8")).decode("ascii"),
        ocr_text=None,
    )

    assert extract_attachment_text(attachment) == "Plain text"


def _make_shp_header_bytes(shape_type: int = 5, bbox: tuple[float, float, float, float] = (7.0, 49.0, 7.5, 49.5)) -> bytes:
    data = bytearray(100)
    struct.pack_into(">i", data, 0, 9994)
    struct.pack_into(">i", data, 24, 50)
    struct.pack_into("<i", data, 28, 1000)
    struct.pack_into("<i", data, 32, shape_type)
    struct.pack_into("<4d", data, 36, *bbox)
    return bytes(data)


def _make_dbf_bytes() -> bytes:
    header = bytearray(65)
    header[0] = 0x03
    header[1] = 26
    header[2] = 11
    header[3] = 11
    struct.pack_into("<I", header, 4, 1)
    struct.pack_into("<H", header, 8, 65)
    struct.pack_into("<H", header, 10, 11)

    field = bytearray(32)
    field[0:4] = b"NAME"
    field[11] = ord("C")
    field[16] = 10
    field[17] = 0
    header[32:64] = field
    header[64] = 0x0D

    record = bytearray(11)
    record[0] = 0x20
    record[1:6] = b"ALPHA"

    return bytes(header + record + b"\x1a")


def test_extract_attachment_text_reads_geo_headers():
    shp = SimpleNamespace(filename="route.shp", mime_type="application/octet-stream", raw_base64=base64.b64encode(_make_shp_header_bytes()).decode("ascii"), data_url=None, ocr_text=None)
    dbf = SimpleNamespace(filename="route.dbf", mime_type="application/octet-stream", raw_base64=base64.b64encode(_make_dbf_bytes()).decode("ascii"), data_url=None, ocr_text=None)
    prj = SimpleNamespace(filename="route.prj", mime_type="application/octet-stream", raw_base64=base64.b64encode(b'GEOGCS["WGS 84"]').decode("ascii"), data_url=None, ocr_text=None)
    cpg = SimpleNamespace(filename="route.cpg", mime_type="application/octet-stream", raw_base64=base64.b64encode(b"UTF-8").decode("ascii"), data_url=None, ocr_text=None)

    shp_text = extract_attachment_text(shp)
    dbf_text = extract_attachment_text(dbf)
    prj_text = extract_attachment_text(prj)
    cpg_text = extract_attachment_text(cpg)

    assert "Geometrietyp: Polygon" in shp_text
    assert "Bounding Box:" in shp_text
    assert "DBF-Attributtabelle" in dbf_text
    assert "Datensatz: 1" in dbf_text
    assert "NAME" in dbf_text
    assert "WGS 84" in prj_text
    assert "UTF-8" in cpg_text


def test_extract_geo_bundle_context_combines_related_files():
    attachments = [
        SimpleNamespace(filename="route.shp", mime_type="application/octet-stream", raw_base64=base64.b64encode(_make_shp_header_bytes()).decode("ascii"), data_url=None, ocr_text=None),
        SimpleNamespace(filename="route.shx", mime_type="application/octet-stream", raw_base64=base64.b64encode(_make_shp_header_bytes()).decode("ascii"), data_url=None, ocr_text=None),
        SimpleNamespace(filename="route.dbf", mime_type="application/octet-stream", raw_base64=base64.b64encode(_make_dbf_bytes()).decode("ascii"), data_url=None, ocr_text=None),
        SimpleNamespace(filename="route.prj", mime_type="application/octet-stream", raw_base64=base64.b64encode(b'GEOGCS["WGS 84"]').decode("ascii"), data_url=None, ocr_text=None),
        SimpleNamespace(filename="route.cpg", mime_type="application/octet-stream", raw_base64=base64.b64encode(b"UTF-8").decode("ascii"), data_url=None, ocr_text=None),
    ]

    text = _extract_geo_bundle_context(attachments, "route.shp")

    assert "Geodatenpaket für 'route'" in text
    assert "Polygon" in text
    assert "1 Datensatz" in text
    assert "WGS 84" in text
    assert "UTF-8" in text
