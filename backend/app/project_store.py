from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from .models import ProjectCreate, ProjectFileEntry, ProjectInventory, ProjectInventorySummary, ProjectRecord
from .settings import get_settings


PROJECT_FOLDERS = ("input", "analysis", "reports", "exports", "notes", "attachments", "chat")


def slugify(value: str) -> str:
    value = value.strip().lower()
    for source, target in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        value = value.replace(source, target)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "project"


def classify_extension(extension: str) -> str:
    match extension.lower().lstrip("."):
        case "gpkg" | "shp" | "geojson" | "json" | "kml" | "kmz" | "csv" | "gdb" | "tif" | "tiff":
            return "geodata"
        case "qgz" | "qgs":
            return "qgis"
        case "doc" | "docx" | "pdf" | "rtf" | "odt" | "ppt" | "pptx":
            return "document"
        case "txt" | "md":
            return "document"
        case "png" | "jpg" | "jpeg" | "webp" | "svg":
            return "image"
        case "zip" | "7z" | "rar":
            return "archive"
        case _:
            return "other"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def system_time_to_iso(timestamp: float) -> str | None:
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    except Exception:
        return None


def normalize_source_path(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return path


def metadata_from_inventory(source: str, source_path: str | None, inventory: ProjectInventory | None) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": source,
        "source_path": source_path,
        "attached": inventory is not None,
    }
    if inventory is None:
        return metadata

    metadata.update(
        {
            "inventory_path": str(Path(inventory.root_path) / "inventory.json"),
            "file_count": inventory.summary.total_files,
            "geodata_count": inventory.summary.geodata_files,
            "document_count": inventory.summary.document_files,
            "image_count": inventory.summary.image_files,
            "qgis_count": inventory.summary.qgis_files,
            "other_count": inventory.summary.other_files,
            "scanned_at": inventory.scanned_at,
        }
    )
    return metadata


class ProjectStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.projects_dir.mkdir(parents=True, exist_ok=True)
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.settings.state_dir / "projects.json"
        if not self.registry_path.exists():
            self.registry_path.write_text("[]", encoding="utf-8")

    def list_projects(self) -> list[ProjectRecord]:
        return [ProjectRecord.model_validate(item) for item in self._load_registry()]

    def get_project(self, project_id: str) -> ProjectRecord:
        for project in self.list_projects():
            if project.id == project_id or project.slug == project_id:
                return project
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden")

    def create_project(self, payload: ProjectCreate) -> ProjectRecord:
        created_at = datetime.now(timezone.utc)
        slug = self._unique_slug(payload.name)
        project_id = uuid.uuid4().hex
        root_path = self.settings.projects_dir / slug
        directories = self._create_project_directories(root_path)
        source_path = normalize_source_path(Path(payload.source_path)) if payload.source_path else None

        record = ProjectRecord(
            id=project_id,
            slug=slug,
            name=payload.name.strip(),
            description=payload.description.strip(),
            client=payload.client.strip(),
            tags=sorted({tag.strip() for tag in payload.tags if tag.strip()}),
            status="active",
            root_path=str(root_path),
            created_at=created_at,
            updated_at=created_at,
            directories={key: str(path) for key, path in directories.items()},
            metadata={"source": "manual", "source_path": str(source_path) if source_path else None},
        )

        if source_path is not None:
            inventory = self._scan_and_store_inventory(record, source_path)
            record.metadata = metadata_from_inventory("manual", str(source_path), inventory)
            record.updated_at = datetime.now(timezone.utc)
            self._write_manifest(record)

        self._save_record(record)
        return record

    def attach_project_folder(self, project_id: str, source_path: str) -> ProjectRecord:
        if not source_path.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ordnerpfad fehlt")

        project = self.get_project(project_id)
        source_root = normalize_source_path(Path(source_path))
        inventory = self._scan_and_store_inventory(project, source_root)
        project.metadata = metadata_from_inventory("attached", str(source_root), inventory)
        project.updated_at = datetime.now(timezone.utc)
        self._write_manifest(project)
        self._save_record(project)
        return project

    def get_project_inventory(self, project_id: str) -> ProjectInventory:
        project = self.get_project(project_id)
        inventory_path = self._project_root(project) / "inventory.json"
        if inventory_path.exists():
            return ProjectInventory.model_validate_json(inventory_path.read_text(encoding="utf-8"))

        source_root = self._project_source_root(project)
        return self._scan_and_store_inventory(project, source_root)

    def refresh_project_inventory(self, project_id: str) -> ProjectInventory:
        project = self.get_project(project_id)
        source_root = self._project_source_root(project)
        inventory = self._scan_and_store_inventory(project, source_root)
        project.updated_at = datetime.now(timezone.utc)
        project.metadata = metadata_from_inventory(project.metadata.get("source", "attached"), project.metadata.get("source_path"), inventory)
        self._write_manifest(project)
        self._save_record(project)
        return inventory

    def _load_registry(self) -> list[dict[str, Any]]:
        return json.loads(self.registry_path.read_text(encoding="utf-8") or "[]")

    def _save_registry(self, records: list[dict[str, Any]]) -> None:
        self.registry_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_record(self, record: ProjectRecord) -> None:
        records = self._load_registry()
        records = [item for item in records if item.get("id") != record.id and item.get("slug") != record.slug]
        records.append(json.loads(record.model_dump_json()))
        self._save_registry(records)

    def _create_project_directories(self, root_path: Path) -> dict[str, Path]:
        root_path.mkdir(parents=True, exist_ok=True)
        directories = {name: root_path / name for name in PROJECT_FOLDERS}
        for path in directories.values():
            path.mkdir(parents=True, exist_ok=True)
        return directories

    def _write_manifest(self, record: ProjectRecord) -> None:
        manifest_path = self._project_root(record) / "manifest.json"
        manifest_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def _scan_and_store_inventory(self, project: ProjectRecord, source_root: Path) -> ProjectInventory:
        if not source_root.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Quellordner nicht gefunden: {source_root}")
        if not source_root.is_dir():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Kein Ordner: {source_root}")

        files: list[ProjectFileEntry] = []
        self._collect_files(source_root, source_root, files)
        files.sort(key=lambda item: item.relative_path)

        summary = ProjectInventorySummary(total_files=len(files))
        for file in files:
            summary.by_extension[file.extension] = summary.by_extension.get(file.extension, 0) + 1
            match file.category:
                case "geodata":
                    summary.geodata_files += 1
                case "document":
                    summary.document_files += 1
                case "image":
                    summary.image_files += 1
                case "qgis":
                    summary.qgis_files += 1
                case _:
                    summary.other_files += 1

        inventory = ProjectInventory(
            project_id=project.id,
            slug=project.slug,
            name=project.name,
            root_path=project.root_path,
            source_path=str(source_root),
            scanned_at=now_iso(),
            summary=summary,
            files=files,
        )

        inventory_path = self._project_root(project) / "inventory.json"
        inventory_path.write_text(inventory.model_dump_json(indent=2), encoding="utf-8")
        return inventory

    def _collect_files(self, root: Path, current: Path, files: list[ProjectFileEntry]) -> None:
        excluded_dirs = {".git", ".venv", "__pycache__", "node_modules", "workspace"}
        for entry in current.iterdir():
            if any(part in excluded_dirs for part in entry.parts):
                continue
            if entry.is_dir():
                self._collect_files(root, entry, files)
                continue
            if not entry.is_file():
                continue
            if entry.name in {"manifest.json", "inventory.json"}:
                continue

            stat = entry.stat()
            relative_path = entry.relative_to(root).as_posix()
            extension = entry.suffix.lower().lstrip(".")
            files.append(
                ProjectFileEntry(
                    relative_path=relative_path,
                    absolute_path=str(entry),
                    file_name=entry.name,
                    extension=extension,
                    category=classify_extension(extension),
                    size_bytes=stat.st_size,
                    modified_at=system_time_to_iso(stat.st_mtime),
                )
            )

    def _project_root(self, record: ProjectRecord) -> Path:
        return Path(record.root_path)

    def _project_source_root(self, record: ProjectRecord) -> Path:
        source_path = record.metadata.get("source_path")
        if isinstance(source_path, str) and source_path.strip():
            return Path(source_path)
        return self._project_root(record)

    def _unique_slug(self, name: str) -> str:
        base_slug = slugify(name)
        slug = base_slug
        counter = 2
        existing = {project.slug for project in self.list_projects()}
        while slug in existing:
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug
