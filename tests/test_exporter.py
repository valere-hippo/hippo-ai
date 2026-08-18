from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from tier_ai.exporter import export_report
from tier_ai.models import AnalysisResult, ClusterSummary, Observation, SpeciesAnalysis


class ExporterTests(unittest.TestCase):
    def test_exports_txt(self) -> None:
        result = AnalysisResult(
            source_path="input.gpkg",
            species_results=[
                SpeciesAnalysis(
                    species="Amsel",
                    total_observations=2,
                    text_summary="Art Amsel: 2 Nachweise im Untersuchungsgebiet.",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = export_report(result, Path(tmpdir) / "bericht.txt")

            self.assertTrue(output.exists())
            self.assertIn("Amsel", output.read_text(encoding="utf-8"))

    def test_exports_pdf(self) -> None:
        result = AnalysisResult(
            source_path="input.gpkg",
            species_results=[
                SpeciesAnalysis(
                    species="Amsel",
                    total_observations=1,
                    text_summary="Art Amsel: 1 Nachweis im Untersuchungsgebiet.",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = export_report(result, Path(tmpdir) / "bericht.pdf")

            self.assertTrue(output.exists())
            content = output.read_bytes()
            self.assertTrue(content.startswith(b"%PDF-1.4"))
            self.assertIn(b"Tier-KI Auswertung", content)
            self.assertIn(b"Zusammenfassung", content)
            self.assertIn(b"Methodik", content)
            self.assertIn(b"Ergebnisprofil", content)
            self.assertIn(b"Schlussbewertung", content)
            self.assertIn(b"hipposideros", content)

    def test_exports_docx(self) -> None:
        result = AnalysisResult(
            source_path="input.gpkg",
            species_results=[
                SpeciesAnalysis(
                    species="Amsel",
                    total_observations=3,
                    taxon_group="bird",
                    clusters=[
                        ClusterSummary(
                            label="Cluster 1",
                            observation_count=3,
                            centroid_x=1.0,
                            centroid_y=2.0,
                        )
                    ],
                    habitat_assessment="habitatlich plausibel für Amsel",
                    reproduction_assessment="vorläufig zu prüfen",
                    concentration_assessment="Verdacht auf Konzentrationszone",
                    recommendation="räumliche Konzentration kartografisch nachprüfen",
                    priority="mittel",
                    text_summary="Art Amsel: 3 Nachweise im Untersuchungsgebiet.",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = export_report(result, Path(tmpdir) / "bericht.docx")

            self.assertTrue(output.exists())
            with ZipFile(output) as archive:
                content_types_xml = archive.read("[Content_Types].xml").decode("utf-8")
                styles_xml = archive.read("word/styles.xml").decode("utf-8")
                numbering_xml = archive.read("word/numbering.xml").decode("utf-8")
                header_xml = archive.read("word/header1.xml").decode("utf-8")
                footer_xml = archive.read("word/footer1.xml").decode("utf-8")
                document_rels_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8")
                logo_svg = archive.read("word/media/logo.svg").decode("utf-8")
                document_xml = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("image/svg+xml", content_types_xml)
                self.assertIn("rIdLogo", document_rels_xml)
                self.assertIn("Tier-KI Auswertung", document_xml)
                self.assertIn("Amsel", document_xml)
                self.assertIn("Methodik", document_xml)
                self.assertIn("Ergebnisprofil", document_xml)
                self.assertIn("wp:inline", document_xml)
                self.assertIn("<w:tbl>", document_xml)
                self.assertIn("Brut", document_xml)
                self.assertIn("Empfehlung", document_xml)
                self.assertIn("Priorität", document_xml)
                self.assertIn("Gruppe", document_xml)
                self.assertIn("headerReference", document_xml)
                self.assertIn("footerReference", document_xml)
                self.assertNotIn("Inhaltsverzeichnis", document_xml)
                self.assertNotIn("TOC \\o \"1-1\" \\h \\z \\u", document_xml)
                self.assertIn("Tier-KI Logo", document_xml)
                self.assertIn("<svg", logo_svg)
                self.assertIn("Title", styles_xml)
                self.assertIn("Heading1", styles_xml)
                self.assertIn("ListBullet", styles_xml)
                self.assertIn("<w:numbering", numbering_xml)
                self.assertIn("Geospatiale Fachauswertung", header_xml)
                self.assertIn("PAGE", footer_xml)

    def test_exports_docx_with_template_overrides(self) -> None:
        result = AnalysisResult(
            source_path="input.gpkg",
            species_results=[
                SpeciesAnalysis(
                    species="Amsel",
                    total_observations=1,
                    text_summary="Art Amsel: 1 Nachweis im Untersuchungsgebiet.",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            template_dir = Path(tmpdir) / "template"
            (template_dir / "word" / "_rels").mkdir(parents=True)
            (template_dir / "docProps").mkdir(parents=True)
            (template_dir / "_rels").mkdir(parents=True)
            (template_dir / "word").mkdir(parents=True, exist_ok=True)
            (template_dir / "[Content_Types].xml").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>
""",
                encoding="utf-8",
            )
            (template_dir / "_rels" / ".rels").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
""",
                encoding="utf-8",
            )
            (template_dir / "docProps" / "core.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"/>
""",
                encoding="utf-8",
            )
            (template_dir / "docProps" / "app.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>
""",
                encoding="utf-8",
            )
            (template_dir / "word" / "styles.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>
</w:styles>
""",
                encoding="utf-8",
            )
            (template_dir / "word" / "numbering.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>
""",
                encoding="utf-8",
            )
            (template_dir / "word" / "header1.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p><w:r><w:t xml:space="preserve">Vorlagenkopf</w:t></w:r></w:p>
</w:hdr>
""",
                encoding="utf-8",
            )
            (template_dir / "word" / "footer1.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:p><w:r><w:t xml:space="preserve">Vorlagenfuß</w:t></w:r></w:p>
</w:ftr>
""",
                encoding="utf-8",
            )
            (template_dir / "word" / "_rels" / "document.xml.rels").write_text(
                """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>
""",
                encoding="utf-8",
            )

            output = export_report(result, Path(tmpdir) / "bericht.docx", docx_template_dir=template_dir)

            self.assertTrue(output.exists())
            with ZipFile(output) as archive:
                header_xml = archive.read("word/header1.xml").decode("utf-8")
                footer_xml = archive.read("word/footer1.xml").decode("utf-8")
                self.assertIn("Vorlagenkopf", header_xml)
                self.assertIn("Vorlagenfuß", footer_xml)


if __name__ == "__main__":
    unittest.main()
