from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import sqlite3
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Any
from io import BytesIO
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    boto3 = None

    class ClientError(Exception):
        pass

from app.core.config import settings
from app.services.chat_payloads import looks_like_project_detailed_report_request
from app.services.pcloud_storage import PCloudEntry, get_pcloud_file_bytes, list_pcloud_folder, has_pcloud_storage, normalize_pcloud_folder_id, normalize_pcloud_path

LOCAL_STORAGE_ROOT = Path("/app/uploads")


@dataclass(slots=True)
class ProjectFile:
    filename: str
    size: int
    modified_at: datetime | None
    storage: str


def _safe_name(value: str | None) -> str:
    candidate = os.path.basename((value or "").strip()) or "attachment"
    candidate = re.sub(r"[^A-Za-z0-9._ -]+", "_", candidate)
    return candidate[:240] or "attachment"


def _normalize_storage_path(value: str | None) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("filename is required")
    raw = raw.lstrip("/")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path traversal is not allowed")
        cleaned = re.sub(r"[^A-Za-z0-9._: -]+", "_", part).strip()
        if not cleaned:
            cleaned = "attachment"
        parts.append(cleaned[:240])
    if not parts:
        raise ValueError("filename is required")
    return "/".join(parts)


def _safe_relative_project_path(value: str | None) -> Path:
    return Path(_normalize_storage_path(value))


def _s3_project_object_path(filename: str) -> str:
    normalized = _normalize_storage_path(filename)
    if normalized.startswith(("sources/", "attachments/")):
        return normalized
    return f"sources/{normalized}"


def _local_project_root(project: Any) -> Path:
    return _local_project_dir(project).resolve()


def _resolve_local_project_file(project: Any, filename: str) -> tuple[Path, str]:
    folders = _local_project_folders(project) or [_local_project_dir(project)]
    rel_input = _safe_relative_project_path(filename)
    filename_text = rel_input.as_posix()

    if len(folders) > 1 and '/' in filename_text:
        prefix, remainder = filename_text.split('/', 1)
        for root in folders:
            if root.name == prefix:
                candidate = (root / remainder).resolve(strict=False)
                if candidate != root and root not in candidate.parents:
                    raise ValueError("path escapes the project folder")
                return candidate, filename_text

    for root in folders:
        candidate = (root / rel_input).resolve(strict=False)
        if candidate == root or root in candidate.parents:
            if candidate.exists():
                return candidate, filename_text if len(folders) == 1 else f"{root.name}/{rel_input.as_posix()}"

    root = folders[0]
    candidate = (root / rel_input).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ValueError("path escapes the project folder")
    return candidate, filename_text if len(folders) == 1 else f"{root.name}/{rel_input.as_posix()}"


def _iter_local_project_files(project: Any) -> list[ProjectFile]:
    folders = _local_project_folders(project) or [_local_project_dir(project)]
    items: list[ProjectFile] = []
    for folder_index, root in enumerate(folders, start=1):
        folder_label = root.name or f"folder-{folder_index}"
        for entry in sorted(root.rglob("*"), key=lambda path: path.as_posix().lower()):
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            rel = entry.relative_to(root).as_posix()
            items.append(
                ProjectFile(
                    filename=f"{folder_label}/{rel}" if len(folders) > 1 else rel,
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    storage="local",
                )
            )
    return items


def _build_local_project_tree_context(project: Any) -> str:
    folders = _local_project_folders(project)
    if not folders:
        root = _local_project_root(project)
        folders = [root]
    lines = [f"Ordnerbaum des gemeinsamen Projektordners: {', '.join(str(folder) for folder in folders)}"]
    for folder_index, root in enumerate(folders, start=1):
        folder_label = root.name or f"folder-{folder_index}"
        lines.append(f"[Ordnerquelle] {folder_label}: {root}")
        for current_root, dirs, files in os.walk(root):
            dirs.sort()
            files.sort()
            current = Path(current_root)
            rel = current.relative_to(root)
            depth = 0 if rel == Path(".") else len(rel.parts)
            indent = "  " * depth
            label = "." if rel == Path(".") else rel.as_posix()
            lines.append(f"{indent}[Ordner] {label}")
            for directory in dirs:
                rel_dir = (rel / directory) if rel != Path(".") else Path(directory)
                lines.append(f"{indent}  [Ordner] {rel_dir.as_posix()}")
            for filename in files:
                rel_file = (rel / filename) if rel != Path(".") else Path(filename)
                try:
                    size = (current / filename).stat().st_size
                except OSError:
                    size = 0
                lines.append(f"{indent}  - {folder_label}/{rel_file.as_posix()} ({size} bytes)")
    return "\n".join(lines)


def _storage_prefix() -> str:
    prefix = (settings.hippo_s3_bucket_prefix or "hippo-ai-").strip().lower()
    prefix = re.sub(r"[^a-z0-9-]+", "-", prefix)
    prefix = prefix.strip("-")
    if prefix and not prefix.endswith("-"):
        prefix += "-"
    return prefix or "hippo-ai-"


def project_bucket_name(project: Any) -> str:
    explicit_bucket = (settings.hippo_s3_bucket_name or "").strip()
    if explicit_bucket:
        return explicit_bucket

    project_id = getattr(project, "id", None)
    if project_id is None:
        raise ValueError("project.id is required for bucket naming")
    bucket = f"{_storage_prefix()}{project_id}"
    bucket = re.sub(r"[^a-z0-9.-]+", "-", bucket.lower())
    bucket = bucket.strip(".-")
    if len(bucket) > 63:
        bucket = bucket[:63].rstrip(".-")
    return bucket


def project_object_prefix(project: Any) -> str:
    return f"{(settings.hippo_s3_key_prefix or 'projects').strip().strip('/')}/{project.id}/"


def has_s3_storage() -> bool:
    return bool(settings.aws_region and settings.aws_access_key_id and settings.aws_secret_access_key)


def can_use_s3_storage() -> bool:
    return has_s3_storage()


def s3_client():
    if not can_use_s3_storage():
        return None
    kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.aws_session_token:
        kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.client("s3", **kwargs)


def _bucket_create_kwargs(bucket: str) -> dict[str, Any]:
    region = (settings.aws_region or "").strip()
    if not region or region == "us-east-1":
        return {"Bucket": bucket}
    return {
        "Bucket": bucket,
        "CreateBucketConfiguration": {"LocationConstraint": region},
    }


def ensure_project_bucket(project: Any) -> str | None:
    client = s3_client()
    if client is None:
        return None

    bucket = project_bucket_name(project)
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound", "403", "400"}:
            raise
        try:
            client.create_bucket(**_bucket_create_kwargs(bucket))
        except ClientError as create_exc:
            create_code = str(create_exc.response.get("Error", {}).get("Code", ""))
            if create_code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise
    return bucket


def delete_project_bucket(project: Any) -> None:
    client = s3_client()
    if client is None:
        return

    bucket = project_bucket_name(project)
    prefix = project_object_prefix(project)
    try:
        listing = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objects = [{"Key": item["Key"]} for item in listing.get("Contents", []) if item.get("Key")]
        if objects:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
        client.delete_bucket(Bucket=bucket)
    except ClientError:
        # Best effort cleanup only.
        return


def clear_project_storage(project: Any) -> dict[str, int]:
    deleted_remote = 0
    deleted_local = 0

    client = s3_client()
    if client is not None:
        bucket = project_bucket_name(project)
        prefix = project_object_prefix(project)
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", []) if item.get("Key")]
                if not objects:
                    continue
                client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
                deleted_remote += len(objects)
        except ClientError:
            pass

    local_dir = LOCAL_STORAGE_ROOT / str(getattr(project, "id", ""))
    if local_dir.exists() and local_dir.is_dir():
        try:
            for entry in local_dir.iterdir():
                if entry.is_file():
                    entry.unlink(missing_ok=True)
                    deleted_local += 1
                elif entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
            try:
                local_dir.rmdir()
            except OSError:
                pass
        except Exception:
            pass

    return {"deleted_remote": deleted_remote, "deleted_local": deleted_local}


def _project_pcloud_reference(project: Any) -> tuple[str | None, int | None]:
    folder_path = getattr(project, "pcloud_path", None)
    folder_id = getattr(project, "pcloud_folder_id", None)
    normalized_path = normalize_pcloud_path(folder_path) if folder_path else None
    normalized_folder_id = normalize_pcloud_folder_id(folder_id)
    return normalized_path, normalized_folder_id


def _project_uses_pcloud(project: Any) -> bool:
    return bool(getattr(project, "pcloud_path", None) and getattr(project, "pcloud_folder_id", None))


def _pcloud_folder_files(project: Any) -> list[PCloudEntry]:
    pcloud_path, pcloud_folder_id = _project_pcloud_reference(project)
    items = list_pcloud_folder(pcloud_path, pcloud_folder_id)
    files: list[PCloudEntry] = []
    for item in items:
        if bool(item.get("isfolder")):
            continue
        name = str(item.get("name") or "").strip()
        path_hint = str(item.get("path") or "").strip()
        if not path_hint:
            base = pcloud_path or "/"
            path_hint = str(PurePosixPath(base) / (name or "attachment"))
        if not name:
            name = PurePosixPath(path_hint).name or path_hint
        modified = item.get("modified") or item.get("created")
        modified_at: datetime | None = None
        if isinstance(modified, str) and modified:
            try:
                modified_at = parsedate_to_datetime(modified)
            except Exception:
                modified_at = None
        files.append(
            PCloudEntry(
                filename=name,
                path=path_hint,
                size=int(item.get("size") or 0),
                modified_at=modified_at,
                is_folder=False,
                file_id=normalize_pcloud_folder_id(item.get("fileid")),
                folder_id=None,
            )
        )
    return files


def _local_project_folders(project: Any) -> list[Path]:
    raw = str(getattr(project, "watched_folder", "") or "").strip()
    if not raw:
        return []
    candidates = [part.strip() for part in re.split(r"[\n;]+", raw) if part.strip()]
    folders: list[Path] = []
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(candidate)
        folders.append(path)
    return folders


def _local_project_dir(project: Any) -> Path:
    project_id = getattr(project, "id", None)
    if project_id is None:
        raise ValueError("project.id is required")

    folders = _local_project_folders(project)
    if folders:
        return folders[0]

    path = LOCAL_STORAGE_ROOT / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_project_file(project: Any, filename: str, content: bytes, content_type: str | None = None, storage_path: str | None = None) -> dict[str, Any]:
    safe_filename = _safe_name(filename)
    if can_use_s3_storage():
        client = s3_client()
        if client is None:
            # Fall back to local storage when S3 is configured but unavailable.
            pass
        else:
            ensure_project_bucket(project)
            object_path = _normalize_storage_path(storage_path or filename)
            key = f"{project_object_prefix(project)}{object_path}"
            client.put_object(
                Bucket=project_bucket_name(project),
                Key=key,
                Body=content,
                ContentType=content_type or mimetypes.guess_type(safe_filename)[0] or "application/octet-stream",
            )
            return {
                "filename": object_path,
                "storage": "s3",
                "bucket": project_bucket_name(project),
                "key": key,
            }

    try:
        path, rel_name = _resolve_local_project_file(project, storage_path or filename)
    except Exception:
        path = _local_project_root(project) / _safe_relative_project_path(storage_path or filename)
        rel_name = _normalize_storage_path(storage_path or filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "filename": rel_name,
        "storage": "local",
        "path": str(path),
    }


def list_project_files(project: Any, source_prefixes: list[str] | None = None) -> list[ProjectFile]:
    normalized_prefixes = [
        _normalize_storage_path(prefix).rstrip('/')
        for prefix in (source_prefixes or [])
        if str(prefix or '').strip()
    ]
    if _project_uses_pcloud(project):
        try:
            files = _pcloud_folder_files(project)
        except Exception:
            return []

        items: list[ProjectFile] = []
        for entry in files:
            if normalized_prefixes and not any(entry.path.lstrip('/').startswith(f'{prefix}/') or entry.path.lstrip('/') == prefix for prefix in normalized_prefixes):
                continue
            items.append(
                ProjectFile(
                    filename=entry.path,
                    size=entry.size,
                    modified_at=entry.modified_at,
                    storage="pcloud",
                )
            )
        return items

    if can_use_s3_storage():
        client = s3_client()
        if client is None:
            return []
        try:
            result = client.list_objects_v2(Bucket=project_bucket_name(project), Prefix=f"{project_object_prefix(project)}sources/")
        except ClientError:
            return []
        items: list[ProjectFile] = []
        prefix = f"{project_object_prefix(project)}sources/"
        for entry in result.get("Contents", []) or []:
            key = entry.get("Key")
            if not key or not key.startswith(prefix):
                continue
            if key.endswith("/"):
                continue
            filename = key[len(prefix):]
            if normalized_prefixes and not any(filename == source or filename.startswith(f'{source}/') for source in normalized_prefixes):
                continue
            items.append(
                ProjectFile(
                    filename=filename,
                    size=int(entry.get("Size") or 0),
                    modified_at=entry.get("LastModified"),
                    storage="s3",
                )
            )
        return items

    return _iter_local_project_files(project)


def read_project_file(project: Any, filename: str) -> tuple[bytes, str, str]:
    safe_filename = _safe_name(filename)
    content_type = mimetypes.guess_type(safe_filename)[0] or "application/octet-stream"

    if _project_uses_pcloud(project):
        path_hint = str(filename or "").strip()
        if not path_hint.startswith("/"):
            pcloud_root, _pcloud_folder_id = _project_pcloud_reference(project)
            if pcloud_root:
                path_hint = str(PurePosixPath(pcloud_root) / path_hint.lstrip("/"))
        body, content_type = get_pcloud_file_bytes(path_hint)
        return body, content_type, "pcloud"

    if can_use_s3_storage():
        client = s3_client()
        if client is None:
            raise RuntimeError("S3 client unavailable")
        key = f"{project_object_prefix(project)}{_s3_project_object_path(filename)}"
        response = client.get_object(Bucket=project_bucket_name(project), Key=key)
        body = response["Body"].read()
        return body, response.get("ContentType") or content_type, "s3"

    path, _rel_name = _resolve_local_project_file(project, filename)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(filename)
    return path.read_bytes(), content_type, "local"


def delete_project_file(project: Any, filename: str) -> dict[str, int | str]:
    safe_filename = _safe_name(filename)
    deleted_remote = 0
    deleted_local = 0
    rel_name = safe_filename

    if can_use_s3_storage():
        client = s3_client()
        if client is not None:
            key = f"{project_object_prefix(project)}{_s3_project_object_path(filename)}"
            try:
                client.delete_object(Bucket=project_bucket_name(project), Key=key)
                deleted_remote = 1
            except ClientError:
                pass

    try:
        local_path, rel_name = _resolve_local_project_file(project, filename)
        if local_path.exists() and local_path.is_file():
            local_path.unlink()
            deleted_local = 1
    except Exception:
        pass

    return {
        "filename": rel_name,
        "deleted_remote": deleted_remote,
        "deleted_local": deleted_local,
    }


def _truncate(text: str, limit: int = 20000) -> str:
    text = re.sub(r"\s+\n", "\n", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""
    return str(value).strip()


def _looks_like_date_field(name: str, field_type: str | None = None) -> bool:
    lowered = (name or "").lower()
    if field_type and field_type.upper() == "D":
        return True
    return any(token in lowered for token in ("date", "datum", "obs", "beob", "time", "zeit", "season", "saison"))


def _parse_date_value(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = _clean_value(value)
    if not text:
        return None
    candidates = [
        "%Y%m%d",
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(text[: len(fmt.replace("%", "")) + 10], fmt)
        except Exception:
            continue
    return None


def _extract_candidates_from_fields(reader: Any, records: list[Any]) -> list[str]:
    fields = [field for field in getattr(reader, "fields", [])[1:]]
    if not fields or not records:
        return []

    scored_fields: list[str] = []
    for field in fields:
        name = field[0]
        lowered = name.lower()
        if any(token in lowered for token in ("species", "spezies", "taxon", "art", "name", "latin", "scient", "common", "spec", "typ")):
            scored_fields.append(name)

    if not scored_fields:
        scored_fields = [field[0] for field in fields[:6]]

    candidates: list[str] = []
    seen: set[str] = set()
    for record in records:
        record_dict = record.as_dict() if hasattr(record, "as_dict") else {}
        for field_name in scored_fields:
            value = _clean_value(record_dict.get(field_name))
            if not value:
                continue
            if value not in seen:
                seen.add(value)
                candidates.append(value)
            if len(candidates) >= 4:
                return candidates
    return candidates


def _grid_label(x_ratio: float, y_ratio: float) -> str:
    if x_ratio < 0.33:
        east_west = "westlich"
    elif x_ratio > 0.66:
        east_west = "östlich"
    else:
        east_west = "zentral"

    if y_ratio < 0.33:
        north_south = "südlich"
    elif y_ratio > 0.66:
        north_south = "nördlich"
    else:
        north_south = "mittig"

    if east_west == "zentral" and north_south == "mittig":
        return "zentral"
    return f"{north_south}-{east_west}"


def _extract_geometry_concentration(reader: Any, bbox: tuple[float, float, float, float] | None) -> str:
    try:
        shapes = reader.shapes()
    except Exception:
        return ""

    if not shapes:
        return ""

    min_x = min_y = max_x = max_y = None
    if bbox:
        min_x, min_y, max_x, max_y = bbox
    else:
        xs = [point[0] for shape in shapes for point in getattr(shape, "points", []) if point]
        ys = [point[1] for shape in shapes for point in getattr(shape, "points", []) if point]
        if not xs or not ys:
            return ""
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

    if min_x is None or min_y is None or max_x is None or max_y is None:
        return ""

    width = max(max_x - min_x, 0.0)
    height = max(max_y - min_y, 0.0)
    if width == 0 and height == 0:
        return "alle Punkte liegen praktisch an derselben Position"

    grid: dict[tuple[int, int], int] = {}
    for shape in shapes:
        points = getattr(shape, "points", []) or []
        if not points:
            continue
        xs = [pt[0] for pt in points if pt]
        ys = [pt[1] for pt in points if pt]
        if not xs or not ys:
            continue
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        x_ratio = 0.5 if width == 0 else min(max((cx - min_x) / width, 0.0), 0.999)
        y_ratio = 0.5 if height == 0 else min(max((cy - min_y) / height, 0.0), 0.999)
        key = (int(x_ratio * 4), int(y_ratio * 4))
        grid[key] = grid.get(key, 0) + 1

    if not grid:
        return ""

    (x_bucket, y_bucket), count = max(grid.items(), key=lambda item: item[1])
    x_ratio = (x_bucket + 0.5) / 4
    y_ratio = (y_bucket + 0.5) / 4
    label = _grid_label(x_ratio, y_ratio)
    return f"Schwerpunkt der Kontakte: {label} innerhalb der Bounding Box ({count} Treffpunkte im dichtesten Rasterfeld)."


def _infer_ecological_hints(fields: list[Any], records: list[Any], species_names: list[str]) -> list[str]:
    hints: list[str] = []
    field_names = [field[0].lower() for field in fields]
    record_dicts = [record.as_dict() if hasattr(record, "as_dict") else {} for record in records[:50]]

    habitat_fields = [name for name in field_names if any(token in name for token in ("habitat", "biotop", "landcover", "land use", "veget", "cover", "struktur", "site", "location", "ort", "area"))]
    breeding_fields = [name for name in field_names if any(token in name for token in ("breed", "brut", "nest", "repro", "kolonie", "territ", "revier", "spawn"))]

    if habitat_fields:
        habitat_values: list[str] = []
        for record in record_dicts:
            for field_name in habitat_fields:
                value = _clean_value(record.get(field_name))
                if value and value not in habitat_values:
                    habitat_values.append(value)
                if len(habitat_values) >= 3:
                    break
            if len(habitat_values) >= 3:
                break
        if habitat_values:
            hints.append(f"Hinweise zu Habitat / Standort: {', '.join(habitat_values[:3])}")

    if breeding_fields:
        breeding_values: list[str] = []
        for record in record_dicts:
            for field_name in breeding_fields:
                value = _clean_value(record.get(field_name))
                if value and value not in breeding_values:
                    breeding_values.append(value)
                if len(breeding_values) >= 3:
                    break
            if len(breeding_values) >= 3:
                break
        if breeding_values:
            hints.append(f"Hinweise zu Revier / Brut / Kolonie: {', '.join(breeding_values[:3])}")

    if species_names:
        if len(species_names) == 1:
            hints.append(f"Vermutlich eine Art im Datensatz: {species_names[0]}")
        else:
            hints.append(f"Vermutlich mehrere Arten / Taxa: {', '.join(species_names[:3])}")

    return hints


def _summarize_date_range(fields: list[Any], records: list[Any]) -> str:
    dates: list[datetime] = []
    for field in fields:
        field_name = field[0]
        field_type = field[1] if len(field) > 1 else None
        if not _looks_like_date_field(field_name, field_type):
            continue
        for record in records:
            record_dict = record.as_dict() if hasattr(record, "as_dict") else {}
            parsed = _parse_date_value(record_dict.get(field_name))
            if parsed:
                dates.append(parsed)

    if not dates:
        return ""

    start = min(dates)
    end = max(dates)
    if start.date() == end.date():
        return f"Beobachtungsdatum: {start.date().isoformat()}"
    return f"Beobachtungszeitraum: {start.date().isoformat()} bis {end.date().isoformat()}"


def _extract_text_from_pdf_bytes(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""

    try:
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        page_count = len(reader.pages)
        for page in reader.pages[:6]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                parts.append(page_text.strip())
        preview = _truncate("\n\n".join(parts))
        if preview:
            return f"PDF mit {page_count} Seiten.\nTextauszug:\n{preview}"
        return f"PDF mit {page_count} Seiten."
    except Exception:
        return ""


def _extract_text_from_docx_bytes(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError):
        return ""

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text_parts = [node.text for node in paragraph.findall(".//w:t", namespace) if node.text]
        line = "".join(text_parts).strip()
        if line:
            paragraphs.append(line)
    preview = _truncate("\n\n".join(paragraphs))
    if preview:
        return f"DOCX mit {len(paragraphs)} Absätzen.\nTextauszug:\n{preview}"
    return f"DOCX mit {len(paragraphs)} Absätzen."


def _extract_text_from_xlsx_bytes(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            if not names:
                return ""
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in names:
                try:
                    shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for si in shared_root.findall(".//main:si", ns):
                        text_parts = [node.text or "" for node in si.findall(".//main:t", ns)]
                        shared_strings.append("".join(text_parts).strip())
                except Exception:
                    shared_strings = []

            ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            parts: list[str] = []
            sheet_names = [name for name in sorted(names) if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
            for sheet_name in sheet_names:
                try:
                    sheet_root = ET.fromstring(archive.read(sheet_name))
                except Exception:
                    continue
                rows: list[str] = []
                for row in sheet_root.findall(".//main:row", ns):
                    cells: list[str] = []
                    for cell in row.findall("main:c", ns):
                        ref = cell.attrib.get("r", "")
                        cell_type = cell.attrib.get("t", "")
                        value = ""
                        if cell_type == "inlineStr":
                            value = "".join(node.text or "" for node in cell.findall(".//main:t", ns)).strip()
                        else:
                            value_node = cell.find("main:v", ns)
                            if value_node is not None and value_node.text is not None:
                                raw = value_node.text.strip()
                                if cell_type == "s" and raw.isdigit():
                                    index = int(raw)
                                    if 0 <= index < len(shared_strings):
                                        value = shared_strings[index]
                                    else:
                                        value = raw
                                else:
                                    value = raw
                        if value:
                            cells.append(f"{ref}={value}")
                    if cells:
                        rows.append("; ".join(cells[:20]))
                if rows:
                    parts.append(f"[{Path(sheet_name).name}]\n" + _truncate("\n".join(rows), 6000))
            preview = _truncate("\n\n".join(parts))
            if preview:
                return f"XLSX mit {len(sheet_names)} Arbeitsblättern.\nTextauszug:\n{preview}"
            return f"XLSX mit {len(sheet_names)} Arbeitsblättern."
    except (BadZipFile, OSError):
        return ""
    except Exception:
        return ""



def _extract_text_from_ods_bytes(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            xml_bytes = archive.read("content.xml")
            root = ET.fromstring(xml_bytes)
    except (BadZipFile, KeyError, OSError, ET.ParseError):
        return ""

    ns = {
        "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
        "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    }
    paragraphs = []
    for node in root.findall(".//text:p", ns):
        line = "".join(node.itertext()).strip()
        if line:
            paragraphs.append(line)
    preview = _truncate("\n\n".join(paragraphs))
    if preview:
        return f"ODS mit {len(paragraphs)} Textabschnitten.\nTextauszug:\n{preview}"
    return f"ODS mit {len(paragraphs)} Textabschnitten."



def _extract_text_from_pptx_bytes(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = [name for name in sorted(archive.namelist()) if name.startswith("ppt/slides/slide") and name.endswith(".xml")]
            if not names:
                return ""
            ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            slides: list[str] = []
            for slide_name in names:
                try:
                    slide_root = ET.fromstring(archive.read(slide_name))
                except Exception:
                    continue
                texts = ["".join(node.itertext()).strip() for node in slide_root.findall(".//a:t", ns)]
                texts = [text for text in texts if text]
                if texts:
                    slides.append(f"[{Path(slide_name).name}]\n" + _truncate("\n".join(texts), 4000))
            preview = _truncate("\n\n".join(slides))
            if preview:
                return f"PPTX mit {len(names)} Folien.\nTextauszug:\n{preview}"
            return f"PPTX mit {len(names)} Folien."
    except (BadZipFile, OSError):
        return ""
    except Exception:
        return ""


AUDIO_FILE_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".webm", ".flac", ".opus"}
VIDEO_FILE_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mpg", ".mpeg"}
MEDIA_FILE_EXTENSIONS = AUDIO_FILE_EXTENSIONS | VIDEO_FILE_EXTENSIONS


def _probe_media_metadata(path: Path) -> str:
    try:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,channels,sample_rate,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
        if proc.returncode != 0 or not proc.stdout.strip():
            return ""
        data = json.loads(proc.stdout)
    except Exception:
        return ""

    lines: list[str] = []
    fmt = data.get("format") or {}
    duration = fmt.get("duration")
    if duration:
        try:
            seconds = float(duration)
            minutes = int(seconds // 60)
            secs = seconds - minutes * 60
            lines.append(f"Dauer: {minutes:02d}:{secs:05.2f}")
        except Exception:
            lines.append(f"Dauer: {duration}s")
    size = fmt.get("size")
    if size:
        try:
            megabytes = int(size) / (1024 * 1024)
            lines.append(f"Größe: {megabytes:.2f} MB")
        except Exception:
            pass
    streams = data.get("streams") or []
    if streams:
        stream_lines = []
        for stream in streams[:8]:
            ctype = stream.get("codec_type") or "stream"
            codec = stream.get("codec_name") or "unknown"
            details = [f"{ctype}:{codec}"]
            if stream.get("width") and stream.get("height"):
                details.append(f"{stream.get('width')}x{stream.get('height')}")
            if stream.get("channels"):
                details.append(f"{stream.get('channels')} ch")
            if stream.get("sample_rate"):
                details.append(f"{stream.get('sample_rate')} Hz")
            if stream.get("avg_frame_rate") and stream.get("avg_frame_rate") != "0/0":
                details.append(f"fps {stream.get('avg_frame_rate')}")
            stream_lines.append(" ".join(details))
        if stream_lines:
            lines.append("Streams: " + "; ".join(stream_lines))
    return "\n".join(lines)


async def _summarize_media_file(project: Any, filename: str) -> str:
    try:
        if _project_uses_pcloud(project):
            data, content_type, _storage = await asyncio.to_thread(read_project_file, project, filename)
        else:
            data, content_type, _storage = read_project_file(project, filename)
    except Exception:
        return ""

    ext = Path(filename).suffix.lower()
    safe_filename = Path(filename).name
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / safe_filename
        try:
            tmp_path.write_bytes(data)
        except Exception:
            return ""

        meta = _probe_media_metadata(tmp_path)
        if ext in AUDIO_FILE_EXTENSIONS:
            try:
                from app.services.speech_to_text import transcribe_audio_file

                transcript = await transcribe_audio_file(tmp_path)
            except Exception:
                transcript = ""
            parts = ["[Audio]"]
            if meta:
                parts.append(meta)
            if transcript:
                parts.append(f"Transkript: {_truncate(transcript, 1500)}")
            return "\n".join(parts).strip()

        if ext in VIDEO_FILE_EXTENSIONS:
            parts = ["[Video]"]
            if meta:
                parts.append(meta)
            parts.append("Hinweis: Video wurde technisch über die Streams und Metadaten erfasst. Für eine inhaltliche Bildanalyse können Einzelbilder aus dem Video extrahiert werden.")
            return "\n".join(parts).strip()

        return meta


def _extract_text_from_plain_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return _truncate(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return ""


def _shape_type_name(shape_type: int) -> str:
    mapping = {
        0: "Null",
        1: "Point",
        3: "PolyLine",
        5: "Polygon",
        8: "MultiPoint",
        11: "PointZ",
        13: "PolyLineZ",
        15: "PolygonZ",
        18: "MultiPointZ",
        21: "PointM",
        23: "PolyLineM",
        25: "PolygonM",
        28: "MultiPointM",
        31: "MultiPatch",
    }
    return mapping.get(shape_type, f"Unknown({shape_type})")


def _parse_shp_header(data: bytes) -> tuple[str | None, tuple[float, float, float, float] | None]:
    if len(data) < 100:
        return None, None
    try:
        shape_type = int.from_bytes(data[32:36], "little", signed=False)
    except Exception:
        return None, None
    try:
        import struct

        x_min, y_min, x_max, y_max = struct.unpack("<4d", data[36:68])
        return _shape_type_name(shape_type), (x_min, y_min, x_max, y_max)
    except Exception:
        return _shape_type_name(shape_type), None


def _extract_shapefile_context(project: Any, stem: str, files_by_name: dict[str, ProjectFile]) -> str:
    related_names = [f"{stem}{ext}" for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg")]
    related_files = [name for name in related_names if name in files_by_name]
    if not related_files:
        return ""

    parts: list[str] = [f"Geodatenpaket für '{stem}':"]
    parts.append(f"- Enthaltene Dateien: {', '.join(related_files)}")

    try:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / stem
            for name in related_files:
                data, _, _ = read_project_file(project, name)
                target = Path(tmpdir) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

            try:
                import shapefile  # type: ignore

                reader = shapefile.Reader(str(base))
                fields = [field for field in getattr(reader, "fields", [])[1:]]
                records = []
                try:
                    records = list(reader.records())
                except Exception:
                    records = []

                shape_type = getattr(reader, "shapeType", None)
                if shape_type is not None:
                    parts.append(f"- Geometrietyp: {_shape_type_name(int(shape_type))}")
                bbox = getattr(reader, "bbox", None)
                if bbox:
                    parts.append(
                        "- Bounding Box: "
                        f"{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}"
                    )
                try:
                    shapes = list(reader.shapes())
                except Exception:
                    shapes = []
                if shapes:
                    parts.append(f"- Geometrien: {len(shapes)} Objekte")
                    sample_summaries = []
                    for idx, shape in enumerate(shapes[:3], start=1):
                        points = _shape_points(shape)
                        if not points:
                            sample_summaries.append(f"Objekt {idx}: keine Punktliste verfügbar")
                            continue
                        first_points = ", ".join(f"{x:.5f}/{y:.5f}" for x, y in points[:3])
                        summary = f"Objekt {idx}: {len(points)} Punkte"
                        if first_points:
                            summary += f"; Startpunkte {first_points}"
                        sample_summaries.append(summary)
                    if sample_summaries:
                        parts.append("- Geometrie-Beispiele: " + " | ".join(sample_summaries))
                if fields:
                    formatted_fields = ", ".join(f"{field[0]} ({field[1]})" for field in fields[:10])
                    parts.append(f"- Felder: {formatted_fields}")
                record_count = getattr(reader, "numRecords", None)
                if record_count is None:
                    record_count = len(records)
                if record_count is not None:
                    parts.append(f"- Kontakte / Datensätze: {record_count}")

                observation_range = _summarize_date_range(fields, records)
                if observation_range:
                    parts.append(f"- {observation_range}")

                species_names = _extract_candidates_from_fields(reader, records)
                if species_names:
                    parts.append(f"- Artenhinweise: {', '.join(species_names[:4])}")

                concentration = _extract_geometry_concentration(reader, bbox if bbox else None)
                if concentration:
                    parts.append(f"- {concentration}")

                ecological_hints = _infer_ecological_hints(fields, records, species_names)
                for hint in ecological_hints:
                    parts.append(f"- {hint}")

                try:
                    if records:
                        first_record = records[0]
                        record_dict = first_record.as_dict() if hasattr(first_record, "as_dict") else {}
                        record_parts = []
                        for field in fields[:8]:
                            field_name = field[0]
                            value = _clean_value(record_dict.get(field_name))
                            if value:
                                record_parts.append(f"{field_name}={value}")
                        if record_parts:
                            parts.append(f"- Beispielinhalt: {', '.join(record_parts)}")
                except Exception:
                    pass
                try:
                    reader.close()
                except Exception:
                    pass
            except Exception:
                shp_path = Path(tmpdir) / f"{stem}.shp"
                if shp_path.exists():
                    data = shp_path.read_bytes()
                    shape_type_name, bbox = _parse_shp_header(data)
                    if shape_type_name:
                        parts.append(f"- Geometrietyp: {shape_type_name}")
                    if bbox:
                        parts.append(
                            "- Bounding Box: "
                            f"{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}"
                        )
                prj_path = Path(tmpdir) / f"{stem}.prj"
                if prj_path.exists():
                    prj_text = _extract_text_from_plain_bytes(prj_path.read_bytes())
                    if prj_text:
                        parts.append(f"- Projektion: {prj_text}")
                dbf_path = Path(tmpdir) / f"{stem}.dbf"
                if dbf_path.exists():
                    parts.append("- DBF vorhanden: Attributtabelle für die Kontakte/Objekte.")
    except Exception:
        return ""

    return "\n".join(parts)


def _extract_gpkg_context(project: Any, filename: str) -> str:
    try:
        data, _, _ = read_project_file(project, filename)
    except Exception:
        return ""


def _find_shapefile_stems(project: Any) -> list[str]:
    stems: list[str] = []
    seen: set[str] = set()
    for item in list_project_files(project):
        if Path(item.filename).suffix.lower() != ".shp":
            continue
        stem = Path(item.filename).with_suffix("").as_posix()
        if stem not in seen:
            seen.add(stem)
            stems.append(stem)
    return stems


def _shape_points(shape: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for point in getattr(shape, "points", []) or []:
        try:
            x, y = float(point[0]), float(point[1])
        except Exception:
            continue
        points.append((x, y))
    return points


def _map_palette(index: int) -> str:
    palette = ["#63d7bf", "#9ab2ff", "#ffd37a", "#ff8fb1", "#8ce6a5", "#d0a0ff"]
    return palette[index % len(palette)]


def _render_geodata_svg(title: str, shape_type: str, shapes: list[Any], records: list[Any], fields: list[Any], bbox: tuple[float, float, float, float] | None) -> str:
    width = 1500
    height = 960
    margin = 72
    panel_w = 320
    map_x0 = margin
    map_y0 = margin
    map_w = width - panel_w - margin * 3
    map_h = height - margin * 2

    all_points = [point for shape in shapes for point in _shape_points(shape)]
    if not all_points and bbox:
        all_points = [(bbox[0], bbox[1]), (bbox[2], bbox[3])]
    if not all_points:
        all_points = [(0.0, 0.0), (1.0, 1.0)]

    xs = [point[0] for point in all_points]
    ys = [point[1] for point in all_points]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    if bbox:
        min_x = min(min_x, bbox[0])
        min_y = min(min_y, bbox[1])
        max_x = max(max_x, bbox[2])
        max_y = max(max_y, bbox[3])

    dx = max(max_x - min_x, 1e-9)
    dy = max(max_y - min_y, 1e-9)
    pad_x = dx * 0.06
    pad_y = dy * 0.06
    min_x -= pad_x
    max_x += pad_x
    min_y -= pad_y
    max_y += pad_y
    dx = max(max_x - min_x, 1e-9)
    dy = max(max_y - min_y, 1e-9)

    def sx(x: float) -> float:
        return map_x0 + ((x - min_x) / dx) * map_w

    def sy(y: float) -> float:
        return map_y0 + map_h - ((y - min_y) / dy) * map_h

    def svg_point(point: tuple[float, float]) -> str:
        return f"{sx(point[0]):.2f},{sy(point[1]):.2f}"

    grid_lines: list[str] = []
    for index in range(6):
        t = index / 5 if 5 else 0
        gx = map_x0 + t * map_w
        gy = map_y0 + t * map_h
        grid_lines.append(f'<line x1="{gx:.2f}" y1="{map_y0:.2f}" x2="{gx:.2f}" y2="{map_y0 + map_h:.2f}" />')
        grid_lines.append(f'<line x1="{map_x0:.2f}" y1="{gy:.2f}" x2="{map_x0 + map_w:.2f}" y2="{gy:.2f}" />')

    shape_markup: list[str] = []
    for idx, shape in enumerate(shapes[:120]):
        points = _shape_points(shape)
        if not points:
            continue
        color = _map_palette(idx)
        shape_type_id = getattr(shape, "shapeType", None)
        if shape_type_id in {1, 8, 11, 18, 21, 28} or (shape_type_id is None and len(points) == 1):
            for point in points:
                shape_markup.append(
                    f'<circle cx="{sx(point[0]):.2f}" cy="{sy(point[1]):.2f}" r="5.5" fill="{color}" stroke="#081118" stroke-width="1.5" />'
                )
        else:
            parts = getattr(shape, "parts", []) or [0]
            boundaries = list(parts) + [len(points)]
            for start, end in zip(boundaries, boundaries[1:]):
                segment = points[start:end]
                if not segment:
                    continue
                path_d = "M " + " L ".join(svg_point(point) for point in segment)
                if shape_type_id in {3, 13, 23}:
                    shape_markup.append(
                        f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.92" />'
                    )
                else:
                    shape_markup.append(
                        f'<path d="{path_d} Z" fill="{color}" fill-opacity="0.24" stroke="{color}" stroke-width="2.8" stroke-linejoin="round" />'
                    )

    labels: list[str] = []
    label_fields = [field for field in fields if any(token in field[0].lower() for token in ("species", "spezies", "taxon", "art", "name", "latin", "common", "spec"))]
    for idx, record in enumerate(records[:8]):
        record_dict = record.as_dict() if hasattr(record, "as_dict") else {}
        label = ""
        for field in label_fields[:3]:
            value = _clean_value(record_dict.get(field[0]))
            if value:
                label = value
                break
        if not label:
            label = f"Feature {idx + 1}"
        points = _shape_points(shapes[idx]) if idx < len(shapes) else []
        if not points:
            continue
        cx = sum(point[0] for point in points) / len(points)
        cy = sum(point[1] for point in points) / len(points)
        labels.append(
            f'<text x="{sx(cx) + 8:.2f}" y="{sy(cy) - 8:.2f}" fill="#edf4fb" font-size="14" font-weight="600" stroke="#081118" stroke-width="3" paint-order="stroke">{xml_escape(label)}</text>'
        )

    coordinate_marks = [
        f'<text x="{map_x0:.2f}" y="{map_y0 + map_h + 28:.2f}" fill="#93a6b8" font-size="12">{min_x:.4f}</text>',
        f'<text x="{map_x0 + map_w - 64:.2f}" y="{map_y0 + map_h + 28:.2f}" fill="#93a6b8" font-size="12">{max_x:.4f}</text>',
        f'<text x="{map_x0 - 8:.2f}" y="{map_y0 + 14:.2f}" fill="#93a6b8" font-size="12">{max_y:.4f}</text>',
        f'<text x="{map_x0 - 8:.2f}" y="{map_y0 + map_h:.2f}" fill="#93a6b8" font-size="12">{min_y:.4f}</text>',
    ]

    legend_items: list[str] = []
    for idx, record in enumerate(records[:6]):
        record_dict = record.as_dict() if hasattr(record, "as_dict") else {}
        summary = []
        for field in fields[:5]:
            value = _clean_value(record_dict.get(field[0]))
            if value:
                summary.append(f"{field[0]}={value}")
        legend_items.append(
            f'<text x="{width - panel_w + 26}" y="{220 + idx * 56}" fill="#c9d7e6" font-size="13">{xml_escape("; ".join(summary) if summary else f"Datensatz {idx + 1}")}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#0a1016"/>
      <stop offset="100%" stop-color="#111a25"/>
    </linearGradient>
    <linearGradient id="panel" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#182331"/>
      <stop offset="100%" stop-color="#111a25"/>
    </linearGradient>
    <style>
      .frame {{ fill: none; stroke: rgba(255,255,255,0.9); stroke-width: 2.2; }}
      .grid {{ stroke: rgba(255,255,255,0.07); stroke-width: 1; }}
    </style>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg)"/>
  <rect x="36" y="36" width="{width - 72}" height="{height - 72}" rx="30" fill="url(#panel)" stroke="rgba(255,255,255,0.88)" stroke-width="2"/>
  <rect x="{map_x0:.2f}" y="{map_y0:.2f}" width="{map_w:.2f}" height="{map_h:.2f}" rx="22" fill="#0f1720" stroke="rgba(99,215,191,0.28)" stroke-width="1.5"/>
  {''.join(grid_lines)}
  {''.join(shape_markup)}
  {''.join(labels)}
  {''.join(coordinate_marks)}
  <rect x="{width - panel_w + 18}" y="60" width="{panel_w - 48}" height="{height - 120}" rx="18" fill="#101923" stroke="rgba(255,255,255,0.08)"/>
  <text x="{width - panel_w + 36}" y="100" fill="#63d7bf" font-size="20" font-weight="700">Hippo AI</text>
  <text x="{width - panel_w + 36}" y="138" fill="#edf4fb" font-size="24" font-weight="700">{xml_escape(title)}</text>
  <text x="{width - panel_w + 36}" y="178" fill="#93a6b8" font-size="13">{xml_escape(shape_type)} · {len(records)} Kontakte</text>
  {''.join(legend_items)}
  <text x="{width - panel_w + 36}" y="{height - 70}" fill="#63d7bf" font-size="12">Koordinatenkarte aus Projektdateien</text>
</svg>'''


def build_geodata_map_file(project: Any, query: str | None = None) -> tuple[str, str] | None:
    stems = _find_shapefile_stems(project)
    if not stems:
        return None

    query_text = (query or "").lower()
    selected_stem = stems[0]
    for stem in stems:
        if stem.lower() in query_text:
            selected_stem = stem
            break

    related_names = [f"{selected_stem}{ext}" for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg")]
    related_files = [name for name in related_names if any(item.filename == name for item in list_project_files(project))]
    if not related_files:
        return None

    try:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / selected_stem
            for name in related_files:
                data, _, _ = read_project_file(project, name)
                target = Path(tmpdir) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)

            import shapefile  # type: ignore

            reader = shapefile.Reader(str(base))
            shapes = list(reader.shapes())
            records = list(reader.records())
            fields = [field for field in getattr(reader, "fields", [])[1:]]
            shape_type = _shape_type_name(int(getattr(reader, "shapeType", 0) or 0))
            bbox = getattr(reader, "bbox", None)
            title = f"{selected_stem.replace('_', ' ').strip() or 'Geodaten'}"
            svg = _render_geodata_svg(title, shape_type, shapes, records, fields, bbox if bbox else None)
            safe_name = re.sub(r"[^A-Za-z0-9]+", "_", selected_stem).strip("_").lower() or "hippo_map"
            return f"{safe_name}.svg", svg
    except Exception:
        return None

    try:
        with TemporaryDirectory() as tmpdir:
            gpkg_path = Path(tmpdir) / filename
            gpkg_path.write_bytes(data)
            conn = sqlite3.connect(str(gpkg_path))
            try:
                cursor = conn.cursor()
                layers = cursor.execute("SELECT table_name, identifier, description FROM gpkg_contents").fetchall()
                geom_columns = cursor.execute(
                    "SELECT table_name, column_name, geometry_type_name, srs_id FROM gpkg_geometry_columns"
                ).fetchall()
                parts = [f"GeoPackage '{filename}':"]
                if layers:
                    parts.append("- Layer: " + ", ".join(row[0] for row in layers[:8]))
                if geom_columns:
                    details = ", ".join(
                        f"{row[0]}.{row[1]} ({row[2]}, SRS {row[3]})" for row in geom_columns[:8]
                    )
                    parts.append(f"- Geometriespalten: {details}")
                for table_name, _, _ in layers[:3]:
                    try:
                        count = cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()
                        if count:
                            parts.append(f"- {table_name}: {count[0]} Datensätze")
                    except Exception:
                        continue
                return "\n".join(parts)
            finally:
                conn.close()
    except Exception:
        return ""


def extract_project_file_preview(filename: str, data: bytes, content_type: str | None = None) -> str:
    safe_filename = (filename or "").lower()
    mime_type = (content_type or mimetypes.guess_type(safe_filename)[0] or "").lower()

    if mime_type == "application/pdf" or safe_filename.endswith(".pdf"):
        return _extract_text_from_pdf_bytes(data)

    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or safe_filename.endswith(".docx"):
        return _extract_text_from_docx_bytes(data)

    if mime_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.oasis.opendocument.spreadsheet",
    } or safe_filename.endswith((".xlsx", ".xlsm", ".xls", ".ods", ".csv")):
        if safe_filename.endswith((".ods",)):
            return _extract_text_from_ods_bytes(data)
        if safe_filename.endswith((".xls",)):
            return _extract_text_from_plain_bytes(data)
        if safe_filename.endswith((".csv",)):
            for encoding in ("utf-8", "utf-16", "latin-1"):
                try:
                    return _truncate(data.decode(encoding))
                except UnicodeDecodeError:
                    continue
            return ""
        return _extract_text_from_xlsx_bytes(data)

    if mime_type in {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.presentation",
    } or safe_filename.endswith((".pptx", ".odp")):
        return _extract_text_from_pptx_bytes(data)

    if mime_type.startswith("text/") or safe_filename.endswith((".txt", ".md", ".log", ".rtf")):
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return _truncate(data.decode(encoding))
            except UnicodeDecodeError:
                continue
        return ""

    if mime_type.startswith("image/") or safe_filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        try:
            from PIL import Image  # type: ignore

            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                mode = image.mode or "unknown"
                fmt = (image.format or "").upper() or "image"
                meta = f"{fmt} {width}x{height} ({mode})"
                ocr_text = ""
                try:
                    import pytesseract  # type: ignore

                    ocr_text = _truncate((pytesseract.image_to_string(image) or "").strip(), 1200)
                except Exception:
                    ocr_text = ""
                if ocr_text:
                    return f"[Bild] {meta}\nOCR: {ocr_text}"
                return f"[Bildmetadaten] {meta}"
        except Exception:
            return "[Image attachment]"

    return ""


IMAGE_FILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


async def build_project_files_context(project: Any, max_files: int | None = None, include_previews: bool = True, question: str | None = None, source_prefixes: list[str] | None = None) -> str:
    detailed_report = looks_like_project_detailed_report_request(question or "")
    try:
        pcloud_path_raw = getattr(project, "pcloud_path", None)
        pcloud_folder_id_raw = getattr(project, "pcloud_folder_id", None)
        if bool(pcloud_path_raw) ^ bool(pcloud_folder_id_raw):
            return (
                "Dieses Projekt ist nur teilweise für pCloud konfiguriert.\n"
                f"pCloud-Pfad: {str(pcloud_path_raw or 'unbekannt').strip()}\n"
                f"pCloud folderid: {pcloud_folder_id_raw or 'unbekannt'}\n"
                "Bitte trage in den Projekteinstellungen sowohl den pCloud-Pfad als auch die folderid ein. Dabei werden nur Dateien im Ordner berücksichtigt; Unterordner werden ignoriert."
            )
        if _project_uses_pcloud(project):
            detailed_report = looks_like_project_detailed_report_request(question or "")
            if not has_pcloud_storage():
                folder = str(getattr(project, "pcloud_path", "") or "").strip()
                folder_id = getattr(project, "pcloud_folder_id", None)
                return (
                    "Dieses Projekt ist auf pCloud konfiguriert, aber der pCloud-Zugang ist auf diesem Server noch nicht eingerichtet.\n"
                    f"pCloud-Pfad: {folder or 'unbekannt'}\n"
                    f"pCloud folderid: {folder_id or 'unbekannt'}\n"
                    "Bitte setze PCLOUD_ACCESS_TOKEN und PCLOUD_API_BASE_URL im Backend. Dabei werden nur Dateien im Ordner berücksichtigt; Unterordner werden ignoriert."
                )
            files = await asyncio.to_thread(_pcloud_folder_files, project)
            if max_files is None or (detailed_report and max_files > 120) or (not detailed_report and max_files > 60):
                max_files = 120 if detailed_report else 60
            files = files[:max_files]
            pcloud_lines = [
                f"Im pCloud-Projektordner sind {len(files)} Dateien sichtbar (Unterordner ignoriert).",
            ]
            preview_budget = 10 if detailed_report else (5 if include_previews else 0)
            preview_max_chars = 800 if detailed_report else 120
            for index, entry in enumerate(files):
                line = f"- {entry.path}"
                if index < preview_budget:
                    try:
                        if _project_uses_pcloud(project):
                            content, content_type, _storage = await asyncio.to_thread(read_project_file, project, entry.path)
                        else:
                            content, content_type, _storage = read_project_file(project, entry.path)
                        summary = extract_project_file_preview(entry.path, content, content_type)
                    except Exception:
                        summary = ""
                    if summary:
                        line += f" — {_truncate(summary, preview_max_chars)}"
                pcloud_lines.append(line)
                if sum(len(part) + 1 for part in pcloud_lines) > 12000:
                    pcloud_lines[-1] = "- … Kontext wegen Länge gekürzt."
                    break
            return "\n".join(pcloud_lines)

        if source_prefixes is not None:
            files = list_project_files(project, source_prefixes=source_prefixes)
            if max_files is not None:
                files = files[:max_files]
            if not files:
                return "Im ausgewählten Ordnersatz sind aktuell keine Dateien sichtbar."
            lines = [f"Im ausgewählten Ordnersatz des Projekts sind {len(files)} sichtbare Dateien vorhanden:"]
            if not _project_uses_pcloud(project):
                try:
                    lines.append(_build_local_project_tree_context(project))
                except Exception:
                    pass
            preview_budget = 10 if detailed_report else (5 if include_previews else 0)
            preview_max_chars = 800 if detailed_report else 180
            for index, item in enumerate(sorted(files, key=lambda entry: entry.filename.lower())):
                line = f"- {item.filename} ({item.size} bytes, Speicherung {item.storage})"
                if index < preview_budget:
                    try:
                        if _project_uses_pcloud(project):
                            content, content_type, _storage = await asyncio.to_thread(read_project_file, project, item.filename)
                        else:
                            content, content_type, _storage = read_project_file(project, item.filename)
                        summary = extract_project_file_preview(item.filename, content, content_type)
                    except Exception:
                        summary = ""
                    if summary:
                        line += f" — {_truncate(summary, preview_max_chars)}"
                lines.append(line)
                if sum(len(part) + 1 for part in lines) > 12000:
                    lines[-1] = "- … Kontext wegen Länge gekürzt."
                    break
            return "\n".join(lines)

        files = list_project_files(project)
    except FileNotFoundError as exc:
        folder = str(getattr(project, "watched_folder", "") or "").strip()
        return (
            "Der gemeinsame Projektordner ist konfiguriert, aber vom Backend aktuell nicht lesbar.\n"
            f"Ordnerpfad: {folder or 'unbekannt'}\n"
            f"Fehler: {exc}\n"
            "Bitte prüfe, ob der Backend-Server Zugriff auf diesen Pfad hat oder ob der Ordner korrekt gemountet wurde."
        )
    except Exception as exc:
        if _project_uses_pcloud(project):
            folder = str(getattr(project, "pcloud_path", "") or "").strip()
            folder_id = getattr(project, "pcloud_folder_id", None)
            return (
                "Der pCloud-Projektpfad konnte aktuell nicht gelesen werden.\n"
                f"pCloud-Pfad: {folder or 'unbekannt'}\n"
                f"pCloud folderid: {folder_id or 'unbekannt'}\n"
                f"Fehler: {exc}\n"
                "Bitte prüfe den pCloud-Zugangstoken, die API-Basis-URL und den Pfad im Projekt. Unterordner werden ignoriert."
            )
        raise

    if max_files is not None:
        files = files[:max_files]
    if not files:
        if _project_uses_pcloud(project):
            folder = str(getattr(project, "pcloud_path", "") or "").strip()
            folder_id = getattr(project, "pcloud_folder_id", None)
            return (
                "Im pCloud-Projektpfad sind aktuell keine Dateien sichtbar.\n"
                f"pCloud-Pfad: {folder or 'unbekannt'}\n"
                f"pCloud folderid: {folder_id or 'unbekannt'}\n"
                "Wenn der Benutzer Dateien erwartet, erkläre ihm bitte, dass der Ordner leer ist oder der Pfad falsch gesetzt ist. Unterordner werden nicht gelesen."
            )
        folder = str(getattr(project, "watched_folder", "") or "").strip()
        try:
            tree_context = _build_local_project_tree_context(project)
        except Exception:
            tree_context = ""
        if tree_context:
            return (
                "Im gemeinsamen Ordner des Projekts sind aktuell keine Dateien sichtbar, aber die Verzeichnisstruktur ist verfügbar.\n"
                f"Ordnerpfad: {folder or 'unbekannt'}\n\n"
                f"{tree_context}"
            )
        return (
            "Im gemeinsamen Ordner des Projekts sind aktuell keine Dateien sichtbar.\n"
            "Wenn der Benutzer Dateien erwartet, erkläre ihm bitte, dass der Ordner leer ist oder die Synchronisierung noch nicht abgeschlossen wurde."
        )

    files_by_name = {item.filename: item for item in files}
    processed: set[str] = set()
    image_summaries: dict[str, asyncio.Task[str]] = {}
    media_summaries: dict[str, asyncio.Task[str]] = {}

    from app.services.vision_analysis import summarize_project_image_file

    for item in files:
        lower_name = item.filename.lower()
        ext = Path(item.filename).suffix.lower()
        if ext in IMAGE_FILE_EXTENSIONS or lower_name.endswith(tuple(IMAGE_FILE_EXTENSIONS)):
            image_summaries[item.filename] = asyncio.create_task(summarize_project_image_file(project, item.filename))
        elif ext in MEDIA_FILE_EXTENSIONS:
            media_summaries[item.filename] = asyncio.create_task(_summarize_media_file(project, item.filename))

    lines = [
        f"Im gemeinsamen Ordner des Projekts sind {len(files)} sichtbare Dateien vorhanden:",
    ]

    if not _project_uses_pcloud(project):
        try:
            lines.append(_build_local_project_tree_context(project))
        except Exception:
            pass

    for item in sorted(files, key=lambda entry: entry.filename.lower()):
        if item.filename in processed:
            continue

        lower_name = item.filename.lower()
        stem = Path(item.filename).with_suffix("").as_posix()
        ext = Path(item.filename).suffix.lower()
        modified = item.modified_at.isoformat(timespec="seconds") if item.modified_at else "unbekannt"

        if ext in {".shp", ".shx", ".dbf", ".prj", ".cpg"}:
            block = _extract_shapefile_context(project, stem, files_by_name)
            if block:
                lines.append(block)
                for related_ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
                    processed.add(f"{stem}{related_ext}")
                continue

        if ext == ".gpkg":
            block = _extract_gpkg_context(project, item.filename)
            if block:
                lines.append(block)
                processed.add(item.filename)
                continue

        summary = ""
        if ext in IMAGE_FILE_EXTENSIONS or lower_name.endswith(tuple(IMAGE_FILE_EXTENSIONS)):
            task = image_summaries.get(item.filename)
            if task is not None:
                try:
                    summary = (await task).strip()
                except Exception:
                    summary = ""
            if not summary:
                try:
                    if _project_uses_pcloud(project):
                        content, content_type, _storage = await asyncio.to_thread(read_project_file, project, item.filename)
                    else:
                        content, content_type, _storage = read_project_file(project, item.filename)
                    summary = extract_project_file_preview(item.filename, content, content_type)
                except Exception:
                    summary = ""
        elif ext in MEDIA_FILE_EXTENSIONS:
            task = media_summaries.get(item.filename)
            if task is not None:
                try:
                    summary = (await task).strip()
                except Exception:
                    summary = ""
            if not summary:
                try:
                    if _project_uses_pcloud(project):
                        content, content_type, _storage = await asyncio.to_thread(read_project_file, project, item.filename)
                    else:
                        content, content_type, _storage = read_project_file(project, item.filename)
                    summary = extract_project_file_preview(item.filename, content, content_type)
                except Exception:
                    summary = ""
        else:
            try:
                if _project_uses_pcloud(project):
                    content, content_type, _storage = await asyncio.to_thread(read_project_file, project, item.filename)
                else:
                    content, content_type, _storage = read_project_file(project, item.filename)
                summary = extract_project_file_preview(item.filename, content, content_type)
            except Exception:
                summary = ""

        lines.append(f"- {item.filename} ({item.size} bytes, Speicherung {item.storage}, geändert {modified})")
        if summary:
            lines.append(f"  Inhalt: {summary}")
        elif lower_name.endswith((".shx", ".dbf", ".prj", ".cpg")):
            lines.append("  Inhalt: Begleitdatei für Geodaten.")
        processed.add(item.filename)
    return "\n".join(lines)
