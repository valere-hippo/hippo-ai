from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import date
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

    def test_exports_docx(self) -> None:
        result = AnalysisResult(
            source_path="input.gpkg",
            species_results=[
                SpeciesAnalysis(
                    species="Amsel",
                    total_observations=3,
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
                    text_summary="Art Amsel: 3 Nachweise im Untersuchungsgebiet.",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = export_report(result, Path(tmpdir) / "bericht.docx")

            self.assertTrue(output.exists())
            with ZipFile(output) as archive:
                styles_xml = archive.read("word/styles.xml").decode("utf-8")
                numbering_xml = archive.read("word/numbering.xml").decode("utf-8")
                document_xml = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("Tier-KI Auswertung", document_xml)
                self.assertIn("Amsel", document_xml)
                self.assertIn("<w:tbl>", document_xml)
                self.assertIn("Brut", document_xml)
                self.assertIn("fldCharType=\"begin\"", document_xml)
                self.assertIn("TOC \\o \"1-1\" \\h \\z \\u", document_xml)
                self.assertIn("Title", styles_xml)
                self.assertIn("Heading1", styles_xml)
                self.assertIn("ListBullet", styles_xml)
                self.assertIn("<w:numbering", numbering_xml)


if __name__ == "__main__":
    unittest.main()
