from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datetime import datetime

from .config import FieldMapping


@dataclass(slots=True)
class ValidationIssue:
    level: str
    message: str


def validate_frame(frame: Any, mapping: FieldMapping | None = None) -> list[ValidationIssue]:
    mapping = mapping or FieldMapping()
    issues: list[ValidationIssue] = []

    species_column = _find_column(frame.columns, [mapping.species, "species", "art", "artname", "taxon"])
    date_column = _find_column(frame.columns, [mapping.observed_at, "date", "datum", "observed_at", "beobachtet_am"])

    if species_column is None:
        issues.append(ValidationIssue(level="error", message="Keine Art-Spalte gefunden."))
    if date_column is None:
        issues.append(ValidationIssue(level="warning", message="Keine Datums-Spalte gefunden."))
    if "geometry" not in {str(column).lower() for column in frame.columns} and getattr(frame, "geometry", None) is None:
        issues.append(ValidationIssue(level="error", message="Keine Geometrie-Spalte gefunden."))

    if not frame.empty and species_column is not None:
        species_values = frame[species_column]
        missing_species = species_values.isna() | species_values.astype(str).map(lambda value: str(value).strip() == "")
        if missing_species.any():
            issues.append(ValidationIssue(level="warning", message="Mindestens ein Datensatz hat keine Artangabe."))

    if not frame.empty and date_column is not None:
        invalid_dates = frame[date_column].map(_looks_like_invalid_date)
        if invalid_dates.any():
            issues.append(ValidationIssue(level="warning", message="Mindestens ein Datensatz hat ein ungültiges Datum."))

    return issues


def _find_column(columns: Any, candidates: list[str]) -> str | None:
    lowered = {str(column).lower(): str(column) for column in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _looks_like_invalid_date(value: Any) -> bool:
    if value in (None, ""):
        return True
    text = str(value).strip()
    if not text:
        return True
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return False
    except ValueError:
        return True
