from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import re


@dataclass(frozen=True, slots=True)
class DesktopActionSpec:
    action: str
    command: str | None = None
    args: str | None = None
    cwd: str | None = None
    file: str | None = None
    path: str | None = None
    keys: str | None = None
    text: str | None = None
    button: str | None = None
    x: float | None = None
    y: float | None = None
    direction: str | None = None
    amount: int | None = None
    wait_seconds: float | None = None


def looks_like_executable_path(value: str) -> bool:
    candidate = (value or '').strip().lower()
    return bool(candidate) and candidate.endswith(('.exe', '.app', '.bat', '.cmd', '.com'))


def looks_qgis_related(text: str) -> bool:
    haystack = (text or '').lower()
    qgis_keywords = (
        'qgis',
        'geo',
        'geodaten',
        'geodata',
        'karte',
        'kart',
        'shp',
        'shx',
        'dbf',
        'prj',
        'cpg',
        'gpkg',
        'geojson',
        'kml',
        'kmz',
        'qgz',
        'qgs',
        'layer',
        'map',
        'maps',
        'shapefile',
        'shape file',
        'shape-file',
    )
    return any(keyword in haystack for keyword in qgis_keywords)


def extract_candidate_open_path(text: str) -> str | None:
    source = text or ''
    executable_patterns = [
        r"[A-Za-z]:\\[^\"\n\r]+?\.(?:exe|app|bat|cmd|com)",
        r"/[^\"\n\r]+?\.(?:exe|app|bat|cmd|com)",
    ]
    for pattern in executable_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip().strip('"').strip("'")

    full_patterns = [
        r"[A-Za-z]:\\[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
        r"/[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
    ]
    for pattern in full_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip().strip('"').strip("'")

    filename_pattern = r"[A-Za-z0-9À-ÿ._-]+\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)"
    filename_matches = list(re.finditer(filename_pattern, source, flags=re.IGNORECASE))
    if not filename_matches:
        return None
    file_match = filename_matches[-1]
    folder_starts = [m for m in re.finditer(r"[A-Za-z]:\\|/", source, flags=re.IGNORECASE) if m.start() < file_match.start()]
    if not folder_starts:
        return None
    folder_start = folder_starts[-1].start()
    prefix = source[folder_start:file_match.start()].rstrip()
    last_sep = max(prefix.rfind('\\'), prefix.rfind('/'))
    if last_sep >= 0:
        head = prefix[:last_sep + 1]
        tail = re.split(r"\s", prefix[last_sep + 1:], 1)[0]
        prefix = f"{head}{tail}"
    prefix = prefix.rstrip('\\/')
    filename = file_match.group(0).strip().strip('"').strip("'")
    separator = '\\' if '\\' in prefix else '/'
    return f"{prefix}{separator}{filename}"


def extract_secondary_data_path(text: str, exclude: str | None = None) -> str | None:
    source = text or ''
    full_patterns = [
        r"[A-Za-z]:\\[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
        r"/[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
    ]
    for pattern in full_patterns:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            candidate = match.group(0).strip().strip('"').strip("'")
            if exclude and candidate == exclude:
                continue
            return candidate

    filename_pattern = r"[A-Za-z0-9À-ÿ._-]+\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)"
    matches = list(re.finditer(filename_pattern, source, flags=re.IGNORECASE))
    if len(matches) < 2:
        return None
    for match in reversed(matches):
        candidate = match.group(0).strip().strip('"').strip("'")
        if exclude and candidate == exclude:
            continue
        return candidate
    return None


def infer_desktop_launch_actions(message: str, reply_text: str, profile: str | None = None) -> list[dict[str, Any]]:
    source = f"{message or ''}\n{reply_text or ''}"
    haystack = source.lower()
    qgis_related = looks_qgis_related(haystack) or (profile or '').strip().lower() == 'qgis'
    if not qgis_related and not any(keyword in haystack for keyword in ('öffne', 'oeffne', 'ouvrir', 'ouvre', 'ouvrir le', 'open', 'starte', 'start', 'launch', 'run', 'lance', 'lancer', 'charge', 'charger', 'öffnen', 'oeffnen', 'öffnest', 'öffnet', 'starten')):
        return []

    open_path = extract_candidate_open_path(source)
    data_path = extract_secondary_data_path(source, exclude=open_path)
    actions: list[DesktopActionSpec] = []
    if open_path:
        if looks_like_executable_path(open_path):
            app_key = 'qgis' if qgis_related else 'word' if ('word' in haystack or 'bericht' in haystack or 'report' in haystack) else 'excel' if 'excel' in haystack else 'libreoffice' if ('libreoffice' in haystack or 'soffice' in haystack) else 'qgis'
            actions.append(DesktopActionSpec(action='launch_app', command=app_key, path=open_path, file=data_path or None))
        elif qgis_related:
            actions.append(DesktopActionSpec(action='launch_app', command='qgis', file=open_path))
        elif 'word' in haystack or 'bericht' in haystack or 'report' in haystack:
            actions.append(DesktopActionSpec(action='launch_app', command='word', file=open_path))
        elif 'excel' in haystack:
            actions.append(DesktopActionSpec(action='launch_app', command='excel', file=open_path))
        elif 'libreoffice' in haystack or 'soffice' in haystack:
            actions.append(DesktopActionSpec(action='launch_app', command='libreoffice', file=open_path))
        else:
            actions.append(DesktopActionSpec(action='open_file', file=open_path))
        return [asdict(item) for item in actions]

    candidates: list[tuple[str, list[str]]] = [
        ('hipponalyze', ['hipponalyze', 'hippo analyze', 'hippo-analyze']),
        ('qgis', ['qgis']),
        ('word', ['word', 'microsoft word']),
        ('excel', ['excel', 'microsoft excel']),
        ('libreoffice', ['libreoffice', 'soffice']),
    ]
    for app_key, needles in candidates:
        if any(needle in haystack for needle in needles):
            return [asdict(DesktopActionSpec(action='launch_app', command=app_key))]

    if qgis_related:
        return [asdict(DesktopActionSpec(action='launch_app', command='qgis'))]

    if profile in {'fledermaus', 'bioacoustics'} and any(needle in haystack for needle in ('fledermaus', 'bat', 'ruf', 'rufe', 'akustik')):
        return [asdict(DesktopActionSpec(action='launch_app', command='hipponalyze'))]

    return []
