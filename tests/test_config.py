from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tier_ai.config import load_analyzer_config


class AnalyzerConfigTests(unittest.TestCase):
    def test_loads_default_config_when_missing_source(self) -> None:
        config = load_analyzer_config()

        self.assertEqual(config.distance_threshold_m, 75.0)
        self.assertEqual(config.min_cluster_size, 2)

    def test_loads_custom_config_file(self) -> None:
        payload = {
            "distance_threshold_m": 120.0,
            "min_cluster_size": 4,
            "distance_threshold_by_group": {
                "bat": 42.0,
            },
            "min_cluster_size_by_group": {
                "bat": 3,
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "analysis.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_analyzer_config(path)

        self.assertEqual(config.distance_threshold_m, 120.0)
        self.assertEqual(config.min_cluster_size, 4)
        self.assertEqual(config.distance_threshold_for("bat"), 42.0)
        self.assertEqual(config.min_cluster_size_for("bat"), 3)


if __name__ == "__main__":
    unittest.main()
