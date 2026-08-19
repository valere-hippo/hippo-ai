from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from .models import UserCreate, UserRecord
from .settings import get_settings


class UserStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.state_dir.mkdir(parents=True, exist_ok=True)
        self.users_path = self.settings.users_path
        self._ensure_bootstrap()

    def list_users(self) -> list[UserRecord]:
        return [UserRecord.model_validate(item) for item in self._load_records()]

    def get_user(self, username: str) -> UserRecord:
        for user in self.list_users():
            if user.username == username:
                return user
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benutzer nicht gefunden")

    def create_user(self, payload: UserCreate) -> UserRecord:
        username = payload.username.strip().lower()
        if not username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Benutzername fehlt")
        if self._user_exists(username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Benutzer existiert bereits")

        now = datetime.now(timezone.utc)
        record = UserRecord(
            username=username,
            display_name=payload.display_name.strip(),
            role=payload.role.strip() or "member",
            password_hash=self._password_hash(username, payload.password),
            active=True,
            created_at=now,
            updated_at=now,
        )
        records = self._load_records()
        records.append(json.loads(record.model_dump_json()))
        self._save_records(records)
        return record

    def verify_credentials(self, username: str, password: str) -> bool:
        try:
            user = self.get_user(username.strip().lower())
        except HTTPException:
            return False
        if not user.active:
            return False
        return user.password_hash == self._password_hash(user.username, password)

    def _ensure_bootstrap(self) -> None:
        if self.users_path.exists():
            return
        now = datetime.now(timezone.utc)
        admin = UserRecord(
            username=self.settings.admin_user.strip().lower(),
            display_name=self.settings.admin_user.strip(),
            role="admin",
            password_hash=self._password_hash(self.settings.admin_user.strip().lower(), self.settings.admin_password),
            active=True,
            created_at=now,
            updated_at=now,
        )
        self._save_records([json.loads(admin.model_dump_json())])

    def _load_records(self) -> list[dict[str, Any]]:
        if not self.users_path.exists():
            return []
        return json.loads(self.users_path.read_text(encoding="utf-8") or "[]")

    def _save_records(self, records: list[dict[str, Any]]) -> None:
        self.users_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    def _user_exists(self, username: str) -> bool:
        return any(user.username == username for user in self.list_users())

    def _password_hash(self, username: str, password: str) -> str:
        secret = self.settings.jwt_secret
        payload = f"{secret}:{username}:{password}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
