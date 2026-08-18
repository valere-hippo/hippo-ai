from tier_ai.models import AnalysisResult, ClusterSummary, InputMetadata, SpeciesAnalysis
from tier_ai.reporter import render_report


def test_render_report_contains_species():
    result = AnalysisResult(
        source_path="input.gpkg",
        executive_summary="Im Datensatz wurden 3 Nachweise aus 1 Arten erfasst.",
        final_conclusion="Die Ergebnisse sollten fachlich gegengeprüft und bei Bedarf kartografisch ergänzt werden.",
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
                display_name="Amsel",
                taxon_group="bird",
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
                recommendation="räumliche Konzentration kartografisch nachprüfen",
                priority="mittel",
                text_summary="Art Amsel: 3 Nachweise im Untersuchungsgebiet.",
            )
        ],
        validation_issues=["Keine Datums-Spalte gefunden."],
    )

    report = render_report(result)

    assert "Amsel" in report
    assert "input.gpkg" in report
    assert "Zusammenfassung" in report
    assert "Methodik" in report
    assert "Ergebnisprofil" in report
    assert "Schlussbewertung" in report
    assert "Übersicht" in report
    assert "Verdacht auf Konzentrationszone" in report
    assert "Habitat" in report
    assert "Transit" in report
    assert "Empfehlung" in report
    assert "Priorität" in report
    assert "Vögel" in report
    assert "Metadaten" in report
    assert "Datenqualität" in report
    assert "Validierung" in report


def test_render_report_formats_unclassified_species_cleanly():
    result = AnalysisResult(
        source_path="input.shp",
        executive_summary="Im Datensatz wurden 3 Nachweise erfasst, die keiner Art eindeutig zugeordnet werden konnten.",
        final_conclusion="Die Nachweise konnten keiner Art eindeutig zugeordnet werden und sollten mit den Originaldaten fachlich nachvalidiert werden.",
        species_results=[
            SpeciesAnalysis(
                species="unbekannt",
                display_name="Nicht zuordenbare Nachweise",
                total_observations=3,
                taxon_group="unknown",
                concentration_assessment="1 Konzentrationsbereich(e), Verdacht auf Konzentrationszone",
                habitat_assessment="unbekannt",
                transit_assessment="für Vogelarten nicht relevant",
                reproduction_assessment="vorläufig zu prüfen",
                recommendation="Revier- oder Konzentrationsraum kartografisch nachprüfen",
                priority="mittel",
                text_summary="Nicht zuordenbare Nachweise: 3 Nachweise im Untersuchungsgebiet.",
            )
        ],
        validation_issues=["Keine Art-Spalte gefunden. Es wird eine unbestimmte Kategorie verwendet."],
    )

    report = render_report(result)

    assert "Nicht zuordenbare Nachweise" in report
    assert "unbestimmt" in report
    assert "unbekannt" not in report
    assert "Methodik" in report
    assert "Ergebnisprofil" in report
    assert "Inhaltsverzeichnis" not in report
