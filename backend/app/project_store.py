from __future__ import annotations

import json
import re
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from .models import (
    ProjectCreate,
    ProjectFileEntry,
    ProjectInventory,
    ProjectInventorySummary,
    ProjectRecord,
    ProjectShareEntry,
    UserContext,
)
from .settings import get_settings
from tier_ai.rules import infer_species_from_filename, infer_species_from_text


PROJECT_FOLDERS = ("input", "analysis", "reports", "exports", "notes", "attachments", "chat")
PROJECT_PERMISSIONS = {"read", "write", "export", "validate"}


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


def metadata_from_inventory(
    source: str,
    source_path: str | None,
    inventory: ProjectInventory | None,
    intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    intelligence = intelligence or {}
    species_hints = intelligence.get("species_hints", [])
    connector_notes = intelligence.get("connector_notes", [])
    qgis_titles = intelligence.get("qgis_titles", [])
    if species_hints:
        metadata["species_hints"] = species_hints
    if connector_notes:
        metadata["connector_notes"] = connector_notes
    if qgis_titles:
        metadata["qgis_titles"] = qgis_titles
    if intelligence:
        metadata["project_intelligence"] = intelligence
    return metadata


class ProjectStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.projects_dir.mkdir(parents=True, exist_ok=True)
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.settings.state_dir / "projects.json"
        if not self.registry_path.exists():
            self.registry_path.write_text("[]", encoding="utf-8")

    def list_projects(self, username: str | None = None, role: str | None = None) -> list[ProjectRecord]:
        projects = [ProjectRecord.model_validate(item) for item in self._load_registry()]
        if not username or (role or "").lower() == "admin":
            return projects
        return [project for project in projects if self.can_access(project, username, "read")]

    def get_project(self, project_id: str) -> ProjectRecord:
        for project in self.list_projects():
            if project.id == project_id or project.slug == project_id:
                return project
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden")

    def get_project_for_user(self, project_id: str, user: UserContext, permission: str = "read") -> ProjectRecord:
        project = self.get_project(project_id)
        if not self.can_access(project, user.username, permission, role=user.role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert")
        return project

    def create_project(self, payload: ProjectCreate, owner_username: str = "") -> ProjectRecord:
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
            owner_username=owner_username.strip().lower(),
            shared_with=[],
        )

        if source_path is not None:
            inventory = self._scan_and_store_inventory(record, source_path)
            record.metadata = metadata_from_inventory(
                "manual",
                str(source_path),
                inventory,
                self._build_project_intelligence(source_path, inventory),
            )
            record.updated_at = datetime.now(timezone.utc)
            self._write_manifest(record)

        self._save_record(record)
        return record

    def attach_project_folder(self, project_id: str, source_path: str, actor: str | None = None) -> ProjectRecord:
        if not source_path.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ordnerpfad fehlt")

        project = self.get_project(project_id)
        if actor and not self.can_access(project, actor, "write"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert")
        source_root = normalize_source_path(Path(source_path))
        inventory = self._scan_and_store_inventory(project, source_root)
        project.metadata = metadata_from_inventory(
            "attached",
            str(source_root),
            inventory,
            self._build_project_intelligence(source_root, inventory),
        )
        project.updated_at = datetime.now(timezone.utc)
        self._write_manifest(project)
        self._save_record(project)
        return project

    def get_project_inventory(self, project_id: str, actor: str | None = None, role: str | None = None) -> ProjectInventory:
        project = self.get_project(project_id)
        if actor and not self.can_access(project, actor, "read", role=role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert")
        inventory_path = self._project_root(project) / "inventory.json"
        if inventory_path.exists():
            return ProjectInventory.model_validate_json(inventory_path.read_text(encoding="utf-8"))

        source_root = self._project_source_root(project)
        return self._scan_and_store_inventory(project, source_root)

    def refresh_project_inventory(self, project_id: str, actor: str | None = None, role: str | None = None) -> ProjectInventory:
        project = self.get_project(project_id)
        if actor and not self.can_access(project, actor, "write", role=role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert")
        source_root = self._project_source_root(project)
        inventory = self._scan_and_store_inventory(project, source_root)
        project.updated_at = datetime.now(timezone.utc)
        project.metadata = metadata_from_inventory(
            project.metadata.get("source", "attached"),
            project.metadata.get("source_path"),
            inventory,
            self._build_project_intelligence(source_root, inventory),
        )
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

    def share_project(self, project_id: str, username: str, permissions: list[str], granted_by: str, replace: bool = False) -> ProjectRecord:
        project = self.get_project(project_id)
        normalized_username = username.strip().lower()
        if not normalized_username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Benutzername fehlt")

        normalized_permissions = self._normalize_permissions(permissions)
        if not normalized_permissions:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Keine Berechtigungen angegeben")

        shares = [share for share in project.shared_with if share.username != normalized_username or not replace]
        if replace:
            shares = [share for share in shares if share.username != normalized_username]
        shares.append(
            ProjectShareEntry(
                username=normalized_username,
                permissions=normalized_permissions,
                granted_by=granted_by.strip().lower(),
                granted_at=datetime.now(timezone.utc),
            )
        )
        project.shared_with = self._deduplicate_shares(shares)
        project.updated_at = datetime.now(timezone.utc)
        self._write_manifest(project)
        self._save_record(project)
        return project

    def revoke_project_access(self, project_id: str, username: str, revoked_by: str) -> ProjectRecord:
        project = self.get_project(project_id)
        normalized_username = username.strip().lower()
        project.shared_with = [share for share in project.shared_with if share.username != normalized_username]
        project.updated_at = datetime.now(timezone.utc)
        self._write_manifest(project)
        self._save_record(project)
        return project

    def get_project_access(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        return {
            "project_id": project.id,
            "owner_username": project.owner_username,
            "shared_with": [json.loads(share.model_dump_json()) for share in project.shared_with],
        }

    def can_access(self, project: ProjectRecord, username: str, permission: str, role: str | None = None) -> bool:
        normalized_username = username.strip().lower()
        if not normalized_username:
            return False
        if (role or "").lower() == "admin":
            return True
        if project.owner_username and project.owner_username.lower() == normalized_username:
            return True
        for share in project.shared_with:
            if share.username.lower() == normalized_username and self._permission_matches(share.permissions, permission):
                return True
        return False

    def can_manage_shares(self, project: ProjectRecord, username: str, role: str | None = None) -> bool:
        normalized_username = username.strip().lower()
        if (role or "").lower() == "admin":
            return True
        return bool(project.owner_username and project.owner_username.lower() == normalized_username)

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

    def _normalize_permissions(self, permissions: list[str]) -> list[str]:
        normalized: list[str] = []
        for permission in permissions:
            value = permission.strip().lower()
            if value in PROJECT_PERMISSIONS and value not in normalized:
                normalized.append(value)
        return normalized

    def _permission_matches(self, granted: list[str], requested: str) -> bool:
        requested_value = requested.strip().lower()
        if requested_value == "read":
            return bool(set(granted) & {"read", "write", "export", "validate"})
        if requested_value == "write":
            return bool(set(granted) & {"write"})
        if requested_value == "export":
            return bool(set(granted) & {"export", "write"})
        if requested_value == "validate":
            return bool(set(granted) & {"validate", "write"})
        return requested_value in granted

    def _deduplicate_shares(self, shares: list[ProjectShareEntry]) -> list[ProjectShareEntry]:
        unique: dict[str, ProjectShareEntry] = {}
        for share in shares:
            unique[share.username.lower()] = share
        return list(unique.values())

    def _build_project_intelligence(self, source_root: Path, inventory: ProjectInventory) -> dict[str, Any]:
        species_hints: list[str] = []
        qgis_titles: list[str] = []
        connector_notes: list[str] = []

        for file in inventory.files:
            hint_candidates = [
                infer_species_from_filename(file.file_name),
                infer_species_from_text(file.relative_path),
                infer_species_from_text(Path(file.relative_path).stem),
            ]
            for hint in hint_candidates:
                if hint and hint not in species_hints:
                    species_hints.append(hint)

            extension = file.extension.lower().lstrip(".")
            file_path = Path(file.absolute_path)

            if extension in {"qgs", "qml", "qgz"}:
                qgis_titles.extend(self._extract_qgis_titles(file_path))
                connector_notes.append(f"QGIS-Datei erkannt: {file.file_name}")

            if extension == "shp":
                bundle_note = self._inspect_shapefile_bundle(file_path)
                if bundle_note:
                    connector_notes.append(bundle_note)

            if extension == "gpkg":
                connector_notes.append(f"GeoPackage erkannt: {file.file_name}")

        intelligence = {
            "species_hints": species_hints[:20],
            "qgis_titles": qgis_titles[:10],
            "connector_notes": connector_notes[:20],
            "source_root": str(source_root),
        }
        if species_hints:
            intelligence["dominant_species"] = species_hints[0]
        return intelligence

    def _extract_qgis_titles(self, path: Path) -> list[str]:
        texts: list[str] = []
        try:
            if path.suffix.lower() == ".qgz":
                with zipfile.ZipFile(path) as archive:
                    for name in archive.namelist():
                        if name.lower().endswith((".qgs", ".qml")):
                            try:
                                texts.append(archive.read(name).decode("utf-8", errors="ignore"))
                            except Exception:
                                continue
            else:
                texts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return []

        titles: list[str] = []
        patterns = [
            re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL),
            re.compile(r'title\s*=\s*"([^"]+)"', re.IGNORECASE),
            re.compile(r"name=\"([^"]+)\"", re.IGNORECASE),
        ]
        for text in texts:
            for pattern in patterns:
                for match in pattern.findall(text):
                    title = str(match).strip()
                    if title and title not in titles:
                        titles.append(title)
        return titles

    def _inspect_shapefile_bundle(self, path: Path) -> str | None:
        base = path.with_suffix("")
        required = [base.with_suffix(ext) for ext in (".shx", ".dbf")]
        optional = [base.with_suffix(ext) for ext in (".prj", ".cpg")]
        missing_required = [file.suffix for file in required if not file.exists()]
        if missing_required:
            return f"Shapefile-Bundle unvollständig für {path.name}: fehlt {', '.join(sorted(missing_required))}"
        present_optional = [file.suffix for file in optional if file.exists()]
        if present_optional:
            return f"Shapefile-Bundle vollständig für {path.name} ({', '.join(sorted(present_optional))} vorhanden)"
        return f"Shapefile-Bundle vollständig für {path.name}"
