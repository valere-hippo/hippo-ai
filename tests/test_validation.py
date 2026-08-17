from __future__ import annotations

import unittest

from tier_ai.config import FieldMapping
from tier_ai.validation import validate_frame


class _Series(list):
    def isna(self):
        return _Series(value is None or value == "" for value in self)

    def astype(self, _type):
        return self

    def map(self, func):
        return _Series(func(value) for value in self)

    def any(self):
        return any(self)

    def __or__(self, other):
        return _Series(a or b for a, b in zip(self, other))

    def __eq__(self, other):
        return _Series(value == other for value in self)


class _Frame:
    def __init__(self, columns, data):
        self.columns = columns
        self._data = data
        self.empty = not bool(data)

    def __getitem__(self, item):
        return _Series(row[item] for row in self._data)


class ValidationTests(unittest.TestCase):
    def test_reports_missing_species_column(self) -> None:
        frame = _Frame(columns=["datum", "geometry"], data=[{"datum": "2026-04-01T00:00:00", "geometry": None}])

        issues = validate_frame(frame, mapping=FieldMapping(species="art", observed_at="datum"))

        self.assertTrue(any(issue.level == "error" for issue in issues))
        self.assertTrue(any("Art-Spalte" in issue.message for issue in issues))

    def test_reports_invalid_date(self) -> None:
        frame = _Frame(columns=["species", "observed_at", "geometry"], data=[{"species": "Amsel", "observed_at": "not-a-date", "geometry": None}])

        issues = validate_frame(frame, mapping=FieldMapping())

        self.assertTrue(any("ungültiges Datum" in issue.message for issue in issues))


if __name__ == "__main__":
    unittest.main()

