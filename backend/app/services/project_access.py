from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any


def normalize_project_folder_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw_values = [part.strip() for part in raw.replace(';', '\n').splitlines() if part.strip()]
    elif isinstance(raw, list):
        raw_values = [str(part).strip() for part in raw if str(part).strip()]
    else:
        raise ValueError('Bitte gültige Quellordner angeben.')

    folders: list[str] = []
    for part in raw_values:
        path = Path(part).expanduser()
        if not (path.is_absolute() or PureWindowsPath(part).is_absolute()):
            raise ValueError('Bitte absolute Quellordner auswählen.')
        folders.append(str(path))
    return list(dict.fromkeys(folders))


def build_default_source_scope(watched_folder: Any) -> dict[str, object] | None:
    folders = normalize_project_folder_list(watched_folder)
    if not folders:
        return None
    return {
        'source_folders': folders,
        'consented': True,
    }
