from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any
import os

import httpx

from app.core.config import settings


@dataclass(slots=True)
class PCloudEntry:
    filename: str
    path: str
    size: int
    modified_at: datetime | None
    is_folder: bool


def has_pcloud_storage() -> bool:
    return bool(settings.pcloud_access_token)


@lru_cache(maxsize=1)
def _resolved_api_base_url() -> str:
    explicit_env = (os.getenv("PCLOUD_API_BASE_URL") or os.getenv("PCLOUD_API_URL") or "").strip()
    if explicit_env:
        return explicit_env.rstrip("/")

    configured = (settings.pcloud_api_base_url or "").strip()
    if configured and configured != "https://api.pcloud.com":
        return configured.rstrip("/")

    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = client.get("https://api.pcloud.com/getapiserver")
            response.raise_for_status()
            payload = response.json()
            servers = payload.get("api") if isinstance(payload, dict) else None
            if isinstance(servers, list):
                for server in servers:
                    candidate = str(server).strip()
                    if candidate:
                        return f"https://{candidate.strip('/')}".rstrip("/")
    except Exception:
        pass

    return configured or "https://eapi.pcloud.com"


def _base_url() -> str:
    return _resolved_api_base_url()


def _auth_headers() -> dict[str, str]:
    token = (settings.pcloud_access_token or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def normalize_pcloud_path(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("pCloud path is required")
    path = PurePosixPath(raw)
    if not raw.startswith("/"):
        path = PurePosixPath("/") / path
    normalized = "/" + str(path).lstrip("/")
    if normalized != "/" and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


def normalize_pcloud_folder_id(value: int | str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        folder_id = int(str(value).strip())
    except Exception as exc:
        raise ValueError("pCloud folderid must be an integer") from exc
    if folder_id <= 0:
        raise ValueError("pCloud folderid must be greater than zero")
    return folder_id


def _api_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
    token = (settings.pcloud_access_token or "").strip()
    if not token:
        raise RuntimeError("pCloud access token is missing")

    url = f"{_base_url()}/{method.lstrip('/')}"
    request_params = dict(params)
    request_params["access_token"] = token
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), headers=_auth_headers()) as client:
        response = client.get(url, params=request_params)
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, dict) and payload.get("result") not in (None, 0):
        raise RuntimeError(str(payload.get("error") or payload.get("message") or f"pCloud error {payload.get('result')}"))
    return payload if isinstance(payload, dict) else {"result": 0, "data": payload}


def list_pcloud_folder(path: str | None = None, folder_id: int | str | None = None) -> list[dict[str, Any]]:
    normalized_folder_id = normalize_pcloud_folder_id(folder_id)
    if normalized_folder_id is not None:
        try:
            payload = _api_call("listfolderbyid", {"folderid": normalized_folder_id})
        except Exception:
            payload = _api_call("listfolder", {"folderid": normalized_folder_id})
    else:
        payload = _api_call("listfolder", {"path": normalize_pcloud_path(path)})
    metadata = payload.get("metadata") or {}
    contents = metadata.get("contents") or []
    if not isinstance(contents, list):
        return []
    return [item for item in contents if isinstance(item, dict)]


def list_pcloud_folder_recursive(path: str | None = None, folder_id: int | str | None = None, max_items: int | None = None, max_depth: int = 32) -> list[PCloudEntry]:
    root_folder_id = normalize_pcloud_folder_id(folder_id)
    root_path = normalize_pcloud_path(path) if path else None
    entries: list[PCloudEntry] = []
    visited: set[str] = set()

    def walk(folder_path: str | None, depth: int = 0, folder_id_value: int | None = None) -> None:
        if depth > max_depth:
            return
        visit_key = f"id:{folder_id_value}" if folder_id_value is not None else f"path:{folder_path}"
        if visit_key in visited:
            return
        visited.add(visit_key)

        try:
            contents = list_pcloud_folder(folder_path, folder_id_value)
        except Exception:
            return

        for item in contents:
            if max_items is not None and len(entries) >= max_items:
                return

            item_path = str(item.get("path") or "").strip() or (folder_path or "")
            item_name = str(item.get("name") or PurePosixPath(item_path).name or item_path).strip() or item_path
            is_folder = bool(item.get("isfolder"))
            size = int(item.get("size") or 0)
            modified = item.get("modified") or item.get("created")
            modified_at: datetime | None = None
            if isinstance(modified, str) and modified:
                try:
                    modified_at = parsedate_to_datetime(modified)
                except Exception:
                    modified_at = None

            entries.append(
                PCloudEntry(
                    filename=item_name,
                    path=item_path,
                    size=size,
                    modified_at=modified_at,
                    is_folder=is_folder,
                )
            )

            if is_folder:
                next_folder_id = normalize_pcloud_folder_id(item.get("folderid"))
                walk(item_path or None, depth + 1, next_folder_id)

    walk(root_path, 0, root_folder_id)
    return entries


def get_pcloud_file_bytes(path: str | None = None, folder_id: int | str | None = None) -> tuple[bytes, str]:
    params: dict[str, Any] = {}
    normalized_folder_id = normalize_pcloud_folder_id(folder_id)
    if normalized_folder_id is not None:
        params["folderid"] = normalized_folder_id
    else:
        params["path"] = normalize_pcloud_path(path)
    payload = _api_call("getfilelink", params)
    hosts = payload.get("hosts") or []
    ppath = str(payload.get("path") or "").strip()
    if not hosts or not ppath:
        raise RuntimeError("pCloud file link unavailable")

    download_url = f"https://{hosts[0]}{ppath}"
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True) as client:
        response = client.get(download_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type") or "application/octet-stream"
        return response.content, content_type
