from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DISTANCE_THRESHOLD_M = 75.0
DEFAULT_MIN_CLUSTER_SIZE = 2


@dataclass(slots=True)
class FieldMapping:
    """Zuordnung der fachlichen Felder zu Layer-Spalten."""

    species: str = "species"
    observed_at: str = "observed_at"


@dataclass(slots=True)
class AnalyzerConfig:
    """Konfigurationsparameter für die räumliche Analyse."""

    distance_threshold_m: float = DEFAULT_DISTANCE_THRESHOLD_M
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE
    distance_threshold_by_group: dict[str, float] = field(default_factory=dict)
    min_cluster_size_by_group: dict[str, int] = field(default_factory=dict)
    field_mapping: FieldMapping = field(default_factory=FieldMapping)

    def distance_threshold_for(self, taxon_group: str) -> float:
        return float(self.distance_threshold_by_group.get(taxon_group.casefold(), self.distance_threshold_m))

    def min_cluster_size_for(self, taxon_group: str) -> int:
        return int(self.min_cluster_size_by_group.get(taxon_group.casefold(), self.min_cluster_size))


def load_analyzer_config(config_source: str | Path | None = None) -> AnalyzerConfig:
    """Lädt Analyseparameter aus einer JSON-Datei.

    Erwartete Schlüssel:
    - distance_threshold_m
    - min_cluster_size
    """

    if config_source is None:
        return AnalyzerConfig()

    payload = json.loads(Path(config_source).read_text(encoding="utf-8"))
    distance_threshold_by_group = {
        str(key).casefold(): float(value)
        for key, value in payload.get("distance_threshold_by_group", {}).items()
    }
    min_cluster_size_by_group = {
        str(key).casefold(): int(value)
        for key, value in payload.get("min_cluster_size_by_group", {}).items()
    }
    return AnalyzerConfig(
        distance_threshold_m=float(payload.get("distance_threshold_m", DEFAULT_DISTANCE_THRESHOLD_M)),
        min_cluster_size=int(payload.get("min_cluster_size", DEFAULT_MIN_CLUSTER_SIZE)),
        distance_threshold_by_group=distance_threshold_by_group,
        min_cluster_size_by_group=min_cluster_size_by_group,
        field_mapping=FieldMapping(),
    )
