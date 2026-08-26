from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from io import BytesIO
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    boto3 = None

    class ClientError(Exception):
        pass

from app.core.config import settings

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
    return has_s3_storage() and boto3 is not None


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


def _local_project_dir(project: Any) -> Path:
    project_id = getattr(project, "id", None)
    if project_id is None:
        raise ValueError("project.id is required")
    path = LOCAL_STORAGE_ROOT / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_project_file(project: Any, filename: str, content: bytes, content_type: str | None = None) -> dict[str, Any]:
    safe_filename = _safe_name(filename)
    if can_use_s3_storage():
        client = s3_client()
        if client is None:
            # Fall back to local storage when S3 is configured but unavailable.
            pass
        else:
            ensure_project_bucket(project)
            key = f"{project_object_prefix(project)}{safe_filename}"
            client.put_object(
                Bucket=project_bucket_name(project),
                Key=key,
                Body=content,
                ContentType=content_type or mimetypes.guess_type(safe_filename)[0] or "application/octet-stream",
            )
            return {
                "filename": safe_filename,
                "storage": "s3",
                "bucket": project_bucket_name(project),
                "key": key,
            }

    path = _local_project_dir(project) / safe_filename
    path.write_bytes(content)
    return {
        "filename": safe_filename,
        "storage": "local",
        "path": str(path),
    }


def list_project_files(project: Any) -> list[ProjectFile]:
    if can_use_s3_storage():
        client = s3_client()
        if client is None:
            return []
        try:
            result = client.list_objects_v2(Bucket=project_bucket_name(project), Prefix=project_object_prefix(project))
        except ClientError:
            return []
        items: list[ProjectFile] = []
        for entry in result.get("Contents", []) or []:
            key = entry.get("Key")
            if not key:
                continue
            if key.endswith("/"):
                continue
            filename = key.split("/")[-1]
            items.append(
                ProjectFile(
                    filename=filename,
                    size=int(entry.get("Size") or 0),
                    modified_at=entry.get("LastModified"),
                    storage="s3",
                )
            )
        return items

    dir_path = _local_project_dir(project)
    items: list[ProjectFile] = []
    for entry in sorted(dir_path.iterdir()):
        if not entry.is_file():
            continue
        stat = entry.stat()
        items.append(
            ProjectFile(
                filename=entry.name,
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                storage="local",
            )
        )
    return items


def read_project_file(project: Any, filename: str) -> tuple[bytes, str, str]:
    safe_filename = _safe_name(filename)
    content_type = mimetypes.guess_type(safe_filename)[0] or "application/octet-stream"

    if can_use_s3_storage():
        client = s3_client()
        if client is None:
            raise RuntimeError("S3 client unavailable")
        key = f"{project_object_prefix(project)}{safe_filename}"
        response = client.get_object(Bucket=project_bucket_name(project), Key=key)
        body = response["Body"].read()
        return body, response.get("ContentType") or content_type, "s3"

    path = _local_project_dir(project) / safe_filename
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(safe_filename)
    return path.read_bytes(), content_type, "local"


def _truncate(text: str, limit: int = 5000) -> str:
    text = re.sub(r"\s+\n", "\n", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _extract_text_from_pdf_bytes(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""

    try:
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        for page in reader.pages[:6]:
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                parts.append(page_text.strip())
        return _truncate("\n\n".join(parts))
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
    return _truncate("\n\n".join(paragraphs))


def extract_project_file_preview(filename: str, data: bytes, content_type: str | None = None) -> str:
    safe_filename = (filename or "").lower()
    mime_type = (content_type or mimetypes.guess_type(safe_filename)[0] or "").lower()

    if mime_type == "application/pdf" or safe_filename.endswith(".pdf"):
        return _extract_text_from_pdf_bytes(data)

    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or safe_filename.endswith(".docx"):
        return _extract_text_from_docx_bytes(data)

    if mime_type.startswith("text/") or safe_filename.endswith((".txt", ".md", ".csv", ".log", ".rtf")):
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
                return f"[Image metadata] {fmt} {width}x{height} ({mode})"
        except Exception:
            return "[Image attachment]"

    return ""


def build_project_files_context(project: Any, max_files: int = 6) -> str:
    files = list_project_files(project)[:max_files]
    if not files:
        return (
            "Im gemeinsamen Ordner des Projekts sind aktuell keine Dateien sichtbar.\n"
            "Wenn der Benutzer Dateien erwartet, erkläre ihm bitte, dass der Bucket leer ist oder die Synchronisierung noch nicht abgeschlossen wurde."
        )

    lines = [
        f"Im gemeinsamen Ordner des Projekts sind {len(files)} sichtbare Dateien vorhanden:",
    ]
    for item in files:
        try:
            content, content_type, _storage = read_project_file(project, item.filename)
            preview = extract_project_file_preview(item.filename, content, content_type)
        except Exception:
            preview = ""

        modified = item.modified_at.isoformat(timespec="seconds") if item.modified_at else "unbekannt"
        lines.append(f"- {item.filename} ({item.size} bytes, Speicherung {item.storage}, geändert {modified})")
        if preview:
            lines.append(f"  Vorschau: {preview}")
    return "\n".join(lines)
