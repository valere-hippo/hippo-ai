from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

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


def s3_client():
    if not has_s3_storage():
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
    if has_s3_storage():
        client = s3_client()
        if client is None:
            raise RuntimeError("S3 client unavailable")
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
    if has_s3_storage():
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

    if has_s3_storage():
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
