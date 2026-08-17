from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(slots=True)
class Observation:
    """Normalisierte Einzelbeobachtung."""

    species: str
    observed_at: date | None
    geometry: Any
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InputSchema:
    """Beschreibung des erwarteten Eingabekontexts."""

    species_column: str = "species"
    observed_at_column: str = "observed_at"
    geometry_column: str = "geometry"
    allowed_species_aliases: list[str] = field(default_factory=lambda: ["species", "art", "artname", "taxon"])
    allowed_date_aliases: list[str] = field(default_factory=lambda: ["date", "datum", "observed_at", "beobachtet_am"])


@dataclass(slots=True)
class ClusterSummary:
    """Zusammenfassung einer räumlichen Häufung."""

    label: str
    observation_count: int
    centroid_x: float
    centroid_y: float
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SpeciesAnalysis:
    """Analyseergebnis pro Art."""

    species: str
    total_observations: int
    clusters: list[ClusterSummary] = field(default_factory=list)
    transit_assessment: str = "nicht bewertet"
    habitat_assessment: str = "unbewertet"
    reproduction_assessment: str = "unbewertet"
    concentration_assessment: str = "unbewertet"
    text_summary: str = ""


@dataclass(slots=True)
class AnalysisResult:
    """Gesamtergebnis für eine Eingabedatei."""

    source_path: str
    metadata: "InputMetadata | None" = None
    executive_summary: str = ""
    species_results: list[SpeciesAnalysis] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    validation_issues: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InputMetadata:
    """Metadaten zur Eingabedatei und zum geladenen Layer."""

    source_name: str
    file_size_bytes: int | None = None
    record_count: int | None = None
    crs: str | None = None
    geometry_types: list[str] = field(default_factory=list)
