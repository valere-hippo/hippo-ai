from __future__ import annotations

import json
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_geojson(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_sample_forest_geojson_contains_known_species():
    payload = _load_geojson("sample_forest.geojson")
    species = [feature["properties"]["species"] for feature in payload["features"]]
    assert payload["type"] == "FeatureCollection"
    assert "Amsel" in species
    assert "Kleiber" in species
    assert "Waldkauz" in species


def test_sample_wetland_geojson_contains_known_species():
    payload = _load_geojson("sample_wetland.geojson")
    species = [feature["properties"]["species"] for feature in payload["features"]]
    assert payload["type"] == "FeatureCollection"
    assert "Rohrdommel" in species
    assert "Teichhuhn" in species
    assert "Weißbartseeschwalbe" in species
