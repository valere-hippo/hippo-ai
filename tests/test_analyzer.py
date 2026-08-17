from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import date

from tier_ai.analyzer import AnalyzerConfig, analyze_observations
from tier_ai.models import Observation


@dataclass
class _Point:
    x: float
    y: float


@dataclass
class _Geometry:
    centroid: _Point


class AnalyzerTests(unittest.TestCase):
    def test_assesses_breeding_in_known_window(self) -> None:
        observations = [
            Observation(
                species="Amsel",
                observed_at=date(2026, 4, 10),
                geometry=_Geometry(_Point(10.0, 10.0)),
                attrs={"habitat": "Gebüsch am Rand"},
            ),
            Observation(
                species="Amsel",
                observed_at=date(2026, 5, 11),
                geometry=_Geometry(_Point(20.0, 20.0)),
                attrs={"habitat": "Hecke"},
            ),
        ]

        result = analyze_observations(
            observations,
            source_path="demo.gpkg",
            config=AnalyzerConfig(distance_threshold_m=50.0, min_cluster_size=2),
        )
        species = result.species_results[0]

        self.assertEqual(species.species, "Amsel")
        self.assertIn("Brutverdacht plausibel", species.reproduction_assessment)
        self.assertIn("plausibel", species.habitat_assessment)
        self.assertTrue(species.clusters)
        self.assertEqual(species.priority, "hoch")

    def test_flags_out_of_season_as_non_breeding(self) -> None:
        observations = [
            Observation(
                species="Buntspecht",
                observed_at=date(2026, 1, 5),
                geometry=_Geometry(_Point(0.0, 0.0)),
                attrs={"habitat": "Wiese"},
            ),
            Observation(
                species="Buntspecht",
                observed_at=date(2026, 1, 6),
                geometry=_Geometry(_Point(1.0, 1.0)),
                attrs={"habitat": "Wiese"},
            ),
        ]

        result = analyze_observations(
            observations,
            source_path="demo.gpkg",
            config=AnalyzerConfig(distance_threshold_m=10.0, min_cluster_size=2),
        )
        species = result.species_results[0]

        self.assertIn("kein belastbarer Brutverdacht", species.reproduction_assessment)
        self.assertIn("eher unplausibel", species.habitat_assessment)
        self.assertEqual(species.priority, "mittel")

    def test_assesses_bat_transit(self) -> None:
        observations = [
            Observation(
                species="Zwergfledermaus",
                observed_at=date(2026, 6, 5),
                geometry=_Geometry(_Point(0.0, 0.0)),
                attrs={"habitat": "Hecke entlang Weg", "corridor": "Leitlinie"},
            ),
            Observation(
                species="Zwergfledermaus",
                observed_at=date(2026, 6, 6),
                geometry=_Geometry(_Point(5.0, 5.0)),
                attrs={"habitat": "Gewässerrand", "corridor": "Straße"},
            ),
            Observation(
                species="Zwergfledermaus",
                observed_at=date(2026, 6, 7),
                geometry=_Geometry(_Point(8.0, 6.0)),
                attrs={"habitat": "Hecke", "corridor": "Brücke"},
            ),
        ]

        result = analyze_observations(
            observations,
            source_path="demo.gpkg",
            config=AnalyzerConfig(distance_threshold_m=10.0, min_cluster_size=2),
        )
        species = result.species_results[0]

        self.assertIn("Transit", species.transit_assessment)
        self.assertIn("Zwergfledermaus", species.transit_assessment)
        self.assertEqual(species.priority, "hoch")

    def test_uses_group_specific_cluster_thresholds(self) -> None:
        observations = [
            Observation(
                species="Amsel",
                observed_at=date(2026, 4, 10),
                geometry=_Geometry(_Point(0.0, 0.0)),
                attrs={"habitat": "Hecke"},
            ),
            Observation(
                species="Amsel",
                observed_at=date(2026, 4, 11),
                geometry=_Geometry(_Point(20.0, 20.0)),
                attrs={"habitat": "Hecke"},
            ),
            Observation(
                species="Zwergfledermaus",
                observed_at=date(2026, 6, 5),
                geometry=_Geometry(_Point(0.0, 0.0)),
                attrs={"habitat": "Hecke entlang Weg", "corridor": "Leitlinie"},
            ),
            Observation(
                species="Zwergfledermaus",
                observed_at=date(2026, 6, 6),
                geometry=_Geometry(_Point(20.0, 0.0)),
                attrs={"habitat": "Gewässerrand", "corridor": "Leitlinie"},
            ),
            Observation(
                species="Zwergfledermaus",
                observed_at=date(2026, 6, 7),
                geometry=_Geometry(_Point(22.0, 1.0)),
                attrs={"habitat": "Hecke", "corridor": "Leitlinie"},
            ),
        ]

        config = AnalyzerConfig(
            distance_threshold_m=15.0,
            min_cluster_size=2,
            distance_threshold_by_group={"bat": 25.0, "bird": 15.0},
            min_cluster_size_by_group={"bat": 3, "bird": 2},
        )
        result = analyze_observations(observations, source_path="demo.gpkg", config=config)
        species_by_name = {species.species: species for species in result.species_results}

        self.assertFalse(species_by_name["Amsel"].clusters)
        self.assertTrue(species_by_name["Zwergfledermaus"].clusters)
        self.assertEqual(species_by_name["Zwergfledermaus"].clusters[0].notes[0], "Abstandsschwelle 25.0 m")


if __name__ == "__main__":
    unittest.main()
