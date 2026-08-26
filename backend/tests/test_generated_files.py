from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import app.services.generated_files as generated_files
from app.services.generated_files import build_generated_file_bytes
from app.services.generated_files import extract_generated_files


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


def test_extract_generated_files_accepts_missing_end_marker():
    files, cleaned = extract_generated_files(
        "Avant.\n<<<FILE:jesus.png>>>\nEine 16:9 Bildbeschreibung mit Licht und Kraft.\nNoch mehr Details.\nNachher."
    )

    assert len(files) == 1
    assert files[0].filename == "jesus.png"
    assert "16:9" in files[0].content
    assert "Avant." in cleaned
    assert "Nachher." in cleaned


def test_build_generated_png_falls_back_without_pillow(monkeypatch):
    monkeypatch.setattr(generated_files, "Image", None)
    monkeypatch.setattr(generated_files, "ImageDraw", None)
    monkeypatch.setattr(generated_files, "ImageFont", None)

    data, mime_type, filename = generated_files.build_generated_file_bytes_with_fallback("jesus.png", "Licht und Kraft")

    assert mime_type == "image/png"
    assert filename.endswith(".png")
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
