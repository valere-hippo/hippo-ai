from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from datetime import datetime

from .config import FieldMapping
from .rules import infer_species_from_filename, infer_species_from_text, load_species_rules, normalize_species_name


@dataclass(slots=True)
class ValidationIssue:
    level: str
    message: str


def validate_frame(frame: Any, mapping: FieldMapping | None = None, source_name: str | None = None) -> list[ValidationIssue]:
    mapping = mapping or FieldMapping()
    issues: list[ValidationIssue] = []

    species_column = detect_species_column(frame, mapping)
    date_column = _find_column(frame.columns, [mapping.observed_at, "date", "datum", "observed_at", "beobachtet_am"])

    if species_column is None:
        inferred = infer_species_from_filename(source_name) if source_name else None
        if inferred is None:
            issues.append(
                ValidationIssue(
                    level="warning",
                    message="Keine Art-Spalte gefunden und keine Art aus dem Dateinamen ableitbar.",
                )
            )
        else:
            issues.append(
                ValidationIssue(
                    level="info",
                    message=f"Keine Art-Spalte gefunden. Die Art wird aus dem Dateinamen als '{inferred}' abgeleitet.",
                )
            )
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


@lru_cache(maxsize=1)
def _known_species_normalized() -> set[str]:
    rules = load_species_rules()
    normalized = {normalize_species_name(rule.species or key) for key, rule in rules.items()}
    normalized.update(normalize_species_name(key) for key in rules)
    return normalized


def detect_species_column(frame: Any, mapping: FieldMapping | None = None) -> str | None:
    mapping = mapping or FieldMapping()
    direct = _find_column(
        frame.columns,
        [
            mapping.species,
            "species",
            "species_name",
            "art",
            "artname",
            "taxon",
            "taxon_name",
            "wissenschaftlicher_name",
            "deutscher_name",
            "objektart",
            "bezeichnung",
            "name",
        ],
    )
    if direct is not None:
        return direct

    known_species = _known_species_normalized()
    best_column: str | None = None
    best_score = 0
    for column in frame.columns:
        if str(column).lower() == "geometry":
            continue
        try:
            values = [value for value in list(frame[column]) if value not in (None, "")]
        except Exception:
            continue
        if not values:
            continue
        score = 0
        for value in values[:200]:
            resolved = infer_species_from_text(str(value))
            if resolved is not None:
                score += 3
                continue
            text = normalize_species_name(str(value))
            if not text:
                continue
            tokens = [token for token in _tokenize_species_candidate(text) if token]
            if any(token in known_species for token in tokens):
                score += 2
                continue
        if score > best_score:
            best_score = score
            best_column = str(column)

    return best_column if best_score > 0 else None


def _tokenize_species_candidate(value: str) -> list[str]:
    cleaned = value.replace("(", " ").replace(")", " ").replace(",", " ").replace(";", " ").replace("/", " ")
    cleaned = cleaned.replace("|", " ").replace("-", " ").replace("_", " ")
    return [token for token in cleaned.split() if token]


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
