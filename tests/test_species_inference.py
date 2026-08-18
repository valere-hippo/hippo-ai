from __future__ import annotations

import importlib.util
import struct
from pathlib import Path
import unittest

from tier_ai.rules import infer_species_from_filename, resolve_species_label


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _dbf_field_names(path: Path) -> list[str]:
    data = path.read_bytes()
    field_names: list[str] = []
    offset = 32
    while data[offset] != 0x0D:
        field_names.append(data[offset : offset + 11].split(b"\x00", 1)[0].decode("ascii"))
        offset += 32
    return field_names


class SpeciesInferenceTests(unittest.TestCase):
    def test_matches_lazuli_bunting_variants(self) -> None:
        self.assertEqual(infer_species_from_filename("LazuliBuntingBreedingRange12232025.shp"), "Lazulifink")
        self.assertEqual(resolve_species_label("Lazuli Bunting"), "Lazulifink")
        self.assertEqual(resolve_species_label("LazuliBunting"), "Lazulifink")
        self.assertEqual(resolve_species_label("Passerina amoena"), "Lazulifink")

    def test_sample_fixtures_are_speciesless_but_inferable(self) -> None:
        gpkg = FIXTURES / "LazuliBuntingBreedingRange12232025.gpkg"
        shp = FIXTURES / "LazuliBuntingBreedingRange12232025.shp"

        self.assertTrue(gpkg.exists())
        self.assertTrue(shp.exists())
        self.assertIn("note", _dbf_field_names(shp.with_suffix(".dbf")))
        self.assertNotIn("species", _dbf_field_names(shp.with_suffix(".dbf")))
        self.assertEqual(infer_species_from_filename(gpkg.name), "Lazulifink")

    def test_importer_uses_filename_species_fallback_for_speciesless_layers(self) -> None:
        if importlib.util.find_spec("pandas") is None or importlib.util.find_spec("geopandas") is None:
            self.skipTest("geospatial dependencies not installed in this environment")

        from tier_ai.analyzer import analyze_observations
        from tier_ai.importer import load_observations_with_issues

        shp = FIXTURES / "LazuliBuntingBreedingRange12232025.shp"
        observations, issues, metadata = load_observations_with_issues(shp)
        result = analyze_observations(observations, source_path=str(shp))

        self.assertTrue(observations)
        self.assertTrue(metadata.record_count)
        self.assertTrue(any(issue for issue in issues if "Art-Spalte" in issue))
        self.assertEqual(result.species_results[0].display_name, "Lazulifink")
        self.assertNotIn("Nicht zuordenbare Nachweise", {item.display_name for item in result.species_results})
