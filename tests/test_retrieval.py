from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tier_ai.retrieval import RetrievalFilter, index_project, search_project


def _write_geojson(path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "species": "Amsel",
                    "observed_at": "2026-04-01",
                    "zone": "Gebüsch",
                    "note": "Nachweis im dichten Heckenbereich",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [7.0, 51.0],
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "species": "Waldkauz",
                    "observed_at": "2026-04-02",
                    "zone": "Wald",
                    "note": "Altbaumbestand am Rand",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [7.1, 51.1],
                },
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_index_and_search_project_documents() -> None:
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source_root = root / "source"
        source_root.mkdir()
        index_root = root / "index"
        _write_geojson(source_root / "observations.geojson")
        (source_root / "notes.txt").write_text("Amsel und Waldkauz im selben Projekt.", encoding="utf-8")

        summary = index_project(
            project_id="proj-1",
            project_slug="project-1",
            source_root=source_root,
            index_root=index_root,
            use_qdrant=False,
            prefer_real_models=False,
        )

        assert summary.indexed_documents >= 3
        assert summary.backend == "local"

        result = search_project(
            project_id="proj-1",
            project_slug="project-1",
            query="Amsel Gebüsch",
            index_root=index_root,
            filters=RetrievalFilter(species="Amsel", file_type="geojson", limit=5),
            prefer_real_models=False,
        )

        assert result.returned_hits >= 1
        assert any(hit.species == "Amsel" for hit in result.hits)
        assert any("Amsel" in hit.snippet for hit in result.hits)


def test_search_filters_file_type_and_zone() -> None:
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source_root = root / "source"
        source_root.mkdir()
        index_root = root / "index"
        _write_geojson(source_root / "observations.geojson")
        (source_root / "report.txt").write_text("Konzentrationsbereich im Wald", encoding="utf-8")

        index_project(
            project_id="proj-2",
            project_slug="project-2",
            source_root=source_root,
            index_root=index_root,
            use_qdrant=False,
            prefer_real_models=False,
        )

        result = search_project(
            project_id="proj-2",
            project_slug="project-2",
            query="Wald",
            index_root=index_root,
            filters=RetrievalFilter(category="document", file_type="txt", zone=None, limit=5),
            prefer_real_models=False,
        )

        assert result.returned_hits == 1
        assert result.hits[0].file_name == "report.txt"


def test_search_resolves_species_aliases() -> None:
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        source_root = root / "source"
        source_root.mkdir()
        index_root = root / "index"
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "species": "Lazuli Bunting",
                        "observed_at": "2026-05-01",
                        "zone": "Prärie",
                    },
                    "geometry": {"type": "Point", "coordinates": [7.0, 51.0]},
                }
            ],
        }
        (source_root / "lazuli.geojson").write_text(json.dumps(payload), encoding="utf-8")

        index_project(
            project_id="proj-3",
            project_slug="project-3",
            source_root=source_root,
            index_root=index_root,
            use_qdrant=False,
            prefer_real_models=False,
        )

        result = search_project(
            project_id="proj-3",
            project_slug="project-3",
            query="Lazuli Bunting",
            index_root=index_root,
            filters=RetrievalFilter(species="Lazuli Bunting", limit=5),
            prefer_real_models=False,
        )

        assert result.returned_hits >= 1
        assert any(hit.species == "Lazulifink" for hit in result.hits)
