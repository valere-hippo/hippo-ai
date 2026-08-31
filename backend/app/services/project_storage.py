from __future__ import annotations

import mimetypes
import os
import re
import sqlite3
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from io import BytesIO
from tempfile import TemporaryDirectory
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


def delete_project_file(project: Any, filename: str) -> dict[str, int | str]:
    safe_filename = _safe_name(filename)
    deleted_remote = 0
    deleted_local = 0

    if can_use_s3_storage():
        client = s3_client()
        if client is not None:
            key = f"{project_object_prefix(project)}{safe_filename}"
            try:
                client.delete_object(Bucket=project_bucket_name(project), Key=key)
                deleted_remote = 1
            except ClientError:
                pass

    project_id = getattr(project, "id", None)
    local_path = LOCAL_STORAGE_ROOT / str(project_id) / safe_filename if project_id is not None else None
    try:
        if local_path is not None and local_path.exists() and local_path.is_file():
            local_path.unlink()
            deleted_local = 1
    except Exception:
        pass

    return {
        "filename": safe_filename,
        "deleted_remote": deleted_remote,
        "deleted_local": deleted_local,
    }


def _truncate(text: str, limit: int = 5000) -> str:
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
                (Path(tmpdir) / name).write_bytes(data)

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


def build_project_files_context(project: Any, max_files: int = 12) -> str:
    files = list_project_files(project)[:max_files]
    if not files:
        return (
            "Im gemeinsamen Ordner des Projekts sind aktuell keine Dateien sichtbar.\n"
            "Wenn der Benutzer Dateien erwartet, erkläre ihm bitte, dass der Bucket leer ist oder die Synchronisierung noch nicht abgeschlossen wurde."
        )

    files_by_name = {item.filename: item for item in files}
    processed: set[str] = set()

    lines = [
        f"Im gemeinsamen Ordner des Projekts sind {len(files)} sichtbare Dateien vorhanden:",
    ]

    for item in sorted(files, key=lambda entry: entry.filename.lower()):
        if item.filename in processed:
            continue

        lower_name = item.filename.lower()
        stem = Path(item.filename).stem
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

        try:
            content, content_type, _storage = read_project_file(project, item.filename)
            preview = extract_project_file_preview(item.filename, content, content_type)
        except Exception:
            preview = ""

        lines.append(f"- {item.filename} ({item.size} bytes, Speicherung {item.storage}, geändert {modified})")
        if preview:
            lines.append(f"  Inhalt: {preview}")
        elif lower_name.endswith((".shx", ".dbf", ".prj", ".cpg")):
            lines.append("  Inhalt: Begleitdatei für Geodaten.")
        processed.add(item.filename)
    return "\n".join(lines)
