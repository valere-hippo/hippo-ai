from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

if FASTAPI_AVAILABLE:
    from backend.app.project_store import ProjectStore
    from backend.app.models import ProjectCreate
    from backend.app.settings import get_settings
else:  # pragma: no cover - depends on local dev environment
    ProjectStore = None  # type: ignore[assignment]
    ProjectCreate = None  # type: ignore[assignment]
    get_settings = None  # type: ignore[assignment]


class BackendProjectStoreTests(unittest.TestCase):
    @unittest.skipUnless(FASTAPI_AVAILABLE, "fastapi ist lokal nicht installiert")
    def test_create_and_refresh_project_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "workspace"
            source_root = Path(tmpdir) / "source"
            source_root.mkdir()
            (source_root / "observations.geojson").write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {"species": "Amsel", "observed_at": "2026-04-01"},
                                "geometry": {"type": "Point", "coordinates": [7.0, 51.0]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            original_env = {"HIPPO_AI_DATA_ROOT": os.environ.get("HIPPO_AI_DATA_ROOT")}
            try:
                os.environ["HIPPO_AI_DATA_ROOT"] = str(data_root)
                get_settings.cache_clear()
                store = ProjectStore()

                project = store.create_project(
                    ProjectCreate(
                        name="Test Project",
                        description="",
                        client="",
                        tags=[],
                        source_path=str(source_root),
                    )
                )

                inventory = store.get_project_inventory(project.id)
                self.assertGreaterEqual(inventory.summary.total_files, 1)
                self.assertTrue(any(item.file_name == "observations.geojson" for item in inventory.files))

                refreshed = store.refresh_project_inventory(project.id)
                self.assertGreaterEqual(refreshed.summary.total_files, 1)
            finally:
                if original_env["HIPPO_AI_DATA_ROOT"] is None:
                    os.environ.pop("HIPPO_AI_DATA_ROOT", None)
                else:
                    os.environ["HIPPO_AI_DATA_ROOT"] = original_env["HIPPO_AI_DATA_ROOT"]
                get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
