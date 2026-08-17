from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FieldMapping:
    """Zuordnung der fachlichen Felder zu Layer-Spalten."""

    species: str = "species"
    observed_at: str = "observed_at"


@dataclass(slots=True)
class AnalyzerConfig:
    """Konfigurationsparameter für die räumliche Analyse."""

    distance_threshold_m: float = 75.0
    min_cluster_size: int = 2
    field_mapping: FieldMapping = field(default_factory=FieldMapping)

