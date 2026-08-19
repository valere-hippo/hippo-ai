import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from .models import ProjectCreate, ProjectRecord
from .settings import get_settings


PROJECT_FOLDERS = ("input", "analysis", "reports", "exports", "notes", "attachments")


def slugify(value: str) -> str:
    value = value.strip().lower()
    for source, target in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        value = value.replace(source, target)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "project"


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
            metadata={"source": "manual"},
        )

        self._append_record(record)
        self._write_manifest(record)
        return record

    def _create_project_directories(self, root_path: Path) -> dict[str, Path]:
        root_path.mkdir(parents=True, exist_ok=True)
        directories = {name: root_path / name for name in PROJECT_FOLDERS}
        for path in directories.values():
            path.mkdir(parents=True, exist_ok=True)
        return directories

    def _load_registry(self) -> list[dict[str, Any]]:
        return json.loads(self.registry_path.read_text(encoding="utf-8") or "[]")

    def _save_registry(self, records: list[dict[str, Any]]) -> None:
        self.registry_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    def _append_record(self, record: ProjectRecord) -> None:
        records = self._load_registry()
        records = [item for item in records if item.get("id") != record.id and item.get("slug") != record.slug]
        records.append(json.loads(record.model_dump_json()))
        self._save_registry(records)

    def _write_manifest(self, record: ProjectRecord) -> None:
        manifest_path = Path(record.root_path) / "manifest.json"
        manifest_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def _unique_slug(self, name: str) -> str:
        base_slug = slugify(name)
        slug = base_slug
        counter = 2
        existing = {project.slug for project in self.list_projects()}
        while slug in existing:
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

