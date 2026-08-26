from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from app.services.generated_files import build_generated_file_bytes


def _sample_report() -> str:
    return (
        "Wegberg Ordneranalyse Bericht\n"
        "*Erstellt am: 26.08.2026*\n\n"
        "### Einleitung\n"
        "- Punkt eins\n"
        "- Punkt zwei\n\n"
        "### Dateien\n"
        "| Name | Größe |\n"
        "| --- | --- |\n"
        "| a.txt | 12 B |\n"
        "\nDer Ordner enthält außerdem die Datei Überblick und ist sorgfältig strukturiert.\n"
    )


def test_build_generated_docx_contains_structured_text():
    data, mime_type = build_generated_file_bytes("bericht.docx", _sample_report())
    assert mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    with ZipFile(BytesIO(data)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")

    assert "Wegberg Ordneranalyse Bericht" in document_xml
    assert "Professioneller Bericht" in document_xml
    assert "Punkt eins" in document_xml
    assert "**" not in document_xml


def test_build_generated_pdf_contains_title_and_content():
    data, mime_type = build_generated_file_bytes("bericht.pdf", _sample_report())
    assert mime_type == "application/pdf"
    assert data.startswith(b"%PDF-1.4")
    assert b"Wegberg Ordneranalyse Bericht" in data
    assert b"Einleitung" in data
    assert b"\xfc" in data or b"\xf6" in data or b"\xe4" in data
