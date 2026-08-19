from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserContext(BaseModel):
    username: str
    role: str = "admin"


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    client: str = ""
    tags: list[str] = Field(default_factory=list)


class ProjectRecord(BaseModel):
    id: str
    slug: str
    name: str
    description: str = ""
    client: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str = "active"
    root_path: str
    created_at: datetime
    updated_at: datetime
    directories: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BackupResult(BaseModel):
    project_id: str
    archive_path: str
    created_at: datetime
    size_bytes: int


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    workspace_root: str


class AuditEvent(BaseModel):
    timestamp: datetime
    action: str
    subject_type: str
    subject_id: str
    username: str
    details: dict[str, Any] = Field(default_factory=dict)

