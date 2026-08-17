from tier_ai.models import AnalysisResult, ClusterSummary, InputMetadata, SpeciesAnalysis
from tier_ai.reporter import render_report


def test_render_report_contains_species():
    result = AnalysisResult(
        source_path="input.gpkg",
        executive_summary="Im Datensatz wurden 3 Nachweise aus 1 Arten erfasst.",
        metadata=InputMetadata(
            source_name="input.gpkg",
            file_size_bytes=1024,
            record_count=3,
            crs="EPSG:25832",
            geometry_types=["Point"],
        ),
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
                transit_assessment="Transit entlang von Leitstrukturen für Zwergfledermaus plausibel",
                habitat_assessment="habitatlich plausibel für Amsel",
                reproduction_assessment="vorläufig zu prüfen",
                concentration_assessment="Verdacht auf Konzentrationszone",
                text_summary="Art Amsel: 3 Nachweise im Untersuchungsgebiet.",
            )
        ],
        validation_issues=["Keine Datums-Spalte gefunden."],
    )

    report = render_report(result)

    assert "Amsel" in report
    assert "input.gpkg" in report
    assert "Zusammenfassung" in report
    assert "Verdacht auf Konzentrationszone" in report
    assert "Habitat" in report
    assert "Transit" in report
    assert "Metadaten" in report
    assert "Validierung" in report
