from __future__ import annotations

import base64
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from app.services.attachment_processing import extract_attachment_text


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


def test_extract_attachment_text_reads_plain_text():
    attachment = SimpleNamespace(
        filename="readme.txt",
        mime_type="text/plain",
        data_url=None,
        raw_base64=base64.b64encode("Plain text".encode("utf-8")).decode("ascii"),
        ocr_text=None,
    )

    assert extract_attachment_text(attachment) == "Plain text"
