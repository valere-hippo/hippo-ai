from tier_ai.models import AnalysisResult, ClusterSummary, SpeciesAnalysis
from tier_ai.reporter import render_report


def test_render_report_contains_species():
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
                reproduction_assessment="vorläufig zu prüfen",
                concentration_assessment="Verdacht auf Konzentrationszone",
                text_summary="Art Amsel: 3 Nachweise im Untersuchungsgebiet.",
            )
        ],
    )

    report = render_report(result)

    assert "Amsel" in report
    assert "input.gpkg" in report
    assert "Verdacht auf Konzentrationszone" in report

