from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .config import FieldMapping
from .models import InputMetadata, Observation
from .validation import validate_frame


class ImportErrorWithContext(RuntimeError):
    pass


def _configure_shapefile_support() -> None:
    os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")


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
    _configure_shapefile_support()

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
        message = str(exc)
        if source.suffix.lower() == ".shp" and ("shx" in message.lower() or "data sourceerror" in message.lower()):
            raise ImportErrorWithContext(
                f"Die Shape-Datei {source.name} scheint unvollständig zu sein. "
                f"Es fehlt vermutlich die zugehörige .shx-Datei im gleichen Ordner."
            ) from exc
        raise ImportErrorWithContext(f"Datei konnte nicht gelesen werden: {source}") from exc

    if frame.empty:
        return []

    issues = validate_frame(frame, mapping=mapping)
    fatal_issues = [issue for issue in issues if issue.level == "error"]
    if fatal_issues:
        joined = "; ".join(issue.message for issue in fatal_issues)
        raise ImportErrorWithContext(joined)

    species_column = _find_column(
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


def load_observations_with_issues(path: str | Path, mapping: FieldMapping | None = None) -> tuple[list[Observation], list[str], InputMetadata]:
    source = Path(path)
    if not source.exists():
        raise ImportErrorWithContext(f"Datei nicht gefunden: {source}")
    mapping = mapping or FieldMapping()
    _configure_shapefile_support()

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
        message = str(exc)
        if source.suffix.lower() == ".shp" and ("shx" in message.lower() or "data sourceerror" in message.lower()):
            raise ImportErrorWithContext(
                f"Die Shape-Datei {source.name} scheint unvollständig zu sein. "
                f"Es fehlt vermutlich die zugehörige .shx-Datei im gleichen Ordner."
            ) from exc
        raise ImportErrorWithContext(f"Datei konnte nicht gelesen werden: {source}") from exc

    if frame.empty:
        metadata = _build_metadata(source, frame)
        return [], [], metadata

    issues = validate_frame(frame, mapping=mapping)
    fatal_issues = [issue for issue in issues if issue.level == "error"]
    if fatal_issues:
        joined = "; ".join(issue.message for issue in fatal_issues)
        raise ImportErrorWithContext(joined)

    species_column = _find_column(
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

    metadata = _build_metadata(source, frame)
    return observations, [issue.message for issue in issues], metadata


def _build_metadata(source: Path, frame: Any) -> InputMetadata:
    crs_value = getattr(frame, "crs", None)
    geometry_types: list[str] = []
    if not frame.empty:
        geometry_series = getattr(frame, "geometry", [])
        geometry_types = sorted(
            {str(getattr(geometry, "geom_type", "unknown")) for geometry in geometry_series if geometry is not None}
        )

    file_size_bytes = source.stat().st_size if source.exists() else None
    return InputMetadata(
        source_name=source.name,
        file_size_bytes=file_size_bytes,
        record_count=len(frame),
        crs=str(crs_value) if crs_value is not None else None,
        geometry_types=geometry_types,
    )


def _find_column(columns: pd.Index, candidates: list[str]) -> str | None:
    lowered = {str(column).lower(): str(column) for column in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None
