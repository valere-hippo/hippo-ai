from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .models import BackupResult, ProjectRecord
from .settings import get_settings


def create_project_backup(project: ProjectRecord) -> BackupResult:
    settings = get_settings()
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    project_backup_dir = settings.backups_dir / project.slug
    project_backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = project_backup_dir / f"{timestamp}.zip"

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        root_path = Path(project.root_path)
        for path in root_path.rglob("*"):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(root_path))

    return BackupResult(
        project_id=project.id,
        archive_path=str(archive_path),
        created_at=datetime.now(timezone.utc),
        size_bytes=archive_path.stat().st_size,
    )

