from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .config import FieldMapping
from .models import Observation


class ImportErrorWithContext(RuntimeError):
    pass


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def load_observations(path: str | Path, mapping: FieldMapping | None = None) -> list[Observation]:
    """Liest GeoPackage- oder Shape-Daten in ein internes Beobachtungsmodell.

    Erwartet mindestens:
    - eine Spalte für die Art
    - eine Datums-Spalte
    - eine Geometrie
    """

    source = Path(path)
    if not source.exists():
        raise ImportErrorWithContext(f"Datei nicht gefunden: {source}")
    mapping = mapping or FieldMapping()

    try:
        import geopandas as gpd
    except Exception as exc:  # pragma: no cover - import dependency
        raise ImportErrorWithContext(
            "geopandas ist nicht installiert. Für den Import geospatialer Daten "
            "wird diese Abhängigkeit benötigt."
        ) from exc

    try:
        frame = gpd.read_file(source)
    except Exception as exc:
        raise ImportErrorWithContext(f"Datei konnte nicht gelesen werden: {source}") from exc

    if frame.empty:
        return []

    species_column = _find_column(frame.columns, [mapping.species, "species", "art", "artname", "taxon"])
    date_column = _find_column(frame.columns, [mapping.observed_at, "date", "datum", "observed_at", "beobachtet_am"])

    observations: list[Observation] = []
    for _, row in frame.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue

        species = str(row[species_column]).strip() if species_column else "unbekannt"
        observed_at = _parse_date(row[date_column]) if date_column else None
        attrs = row.drop(labels=["geometry"], errors="ignore").to_dict()
        observations.append(
            Observation(
                species=species or "unbekannt",
                observed_at=observed_at,
                geometry=geometry,
                attrs=attrs,
            )
        )

    return observations


def _find_column(columns: pd.Index, candidates: list[str]) -> str | None:
    lowered = {str(column).lower(): str(column) for column in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None
