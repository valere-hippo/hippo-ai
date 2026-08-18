from __future__ import annotations

import sqlite3
import struct
import unittest
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read_dbf_species(path: Path) -> list[str]:
    data = path.read_bytes()
    record_count = struct.unpack_from("<I", data, 4)[0]
    header_length = struct.unpack_from("<H", data, 8)[0]
    record_length = struct.unpack_from("<H", data, 10)[0]

    fields: list[tuple[str, int]] = []
    offset = 32
    while data[offset] != 0x0D:
        name = data[offset : offset + 11].split(b"\x00", 1)[0].decode("ascii")
        field_length = data[offset + 16]
        fields.append((name, field_length))
        offset += 32

    species_index = [name for name, _ in fields].index("species")
    values: list[str] = []
    for idx in range(record_count):
        start = header_length + idx * record_length
        if data[start] == 0x2A:
            continue
        cursor = start + 1
        for field_idx, (_name, field_length) in enumerate(fields):
            raw = data[cursor : cursor + field_length]
            if field_idx == species_index:
                values.append(raw.decode("ascii").strip())
            cursor += field_length
    return values


class SpatialFixtureTests(unittest.TestCase):
    def test_sample_forest_gpkg_contains_expected_species(self) -> None:
        path = FIXTURES / "sample_forest.gpkg"
        self.assertTrue(path.exists())

        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                "select species, observed_at, note, geom from observations order by id"
            ).fetchall()

        species = [row[0] for row in rows]
        self.assertEqual(species, ["Amsel", "Kleiber", "Waldkauz"])
        self.assertTrue(all(blob[:2] == b"GP" for *_, blob in rows))

    def test_sample_forest_shapefile_is_complete_and_contains_species(self) -> None:
        base = FIXTURES / "sample_forest"
        for suffix in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
            self.assertTrue((base.with_suffix(suffix)).exists())

        species = _read_dbf_species(base.with_suffix(".dbf"))
        self.assertEqual(species, ["Amsel", "Kleiber", "Waldkauz"])
