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


class UserRecord(BaseModel):
    username: str
    display_name: str = ""
    role: str = "member"
    password_hash: str = ""
    active: bool = True
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    username: str
    display_name: str = ""
    role: str = "member"
    password: str


class ProjectShareEntry(BaseModel):
    username: str
    permissions: list[str] = Field(default_factory=list)
    granted_by: str = ""
    granted_at: datetime


class ProjectShareRequest(BaseModel):
    username: str
    permissions: list[str] = Field(default_factory=list)
    replace: bool = False


class ProjectAccessView(BaseModel):
    owner_username: str = ""
    shared_with: list[ProjectShareEntry] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    client: str = ""
    tags: list[str] = Field(default_factory=list)
    source_path: str | None = None


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
    owner_username: str = ""
    shared_with: list[ProjectShareEntry] = Field(default_factory=list)


class ProjectFileEntry(BaseModel):
    relative_path: str
    absolute_path: str
    file_name: str
    extension: str
    category: str
    size_bytes: int
    modified_at: str | None = None


class ProjectInventorySummary(BaseModel):
    total_files: int = 0
    geodata_files: int = 0
    document_files: int = 0
    image_files: int = 0
    qgis_files: int = 0
    other_files: int = 0
    by_extension: dict[str, int] = Field(default_factory=dict)


class ProjectInventory(BaseModel):
    project_id: str
    slug: str
    name: str
    root_path: str
    source_path: str | None = None
    scanned_at: str
    summary: ProjectInventorySummary
    files: list[ProjectFileEntry] = Field(default_factory=list)


class RetrievalIndexRequest(BaseModel):
    source_root: str | None = None
    index_root: str | None = None
    use_qdrant: bool = True
    prefer_real_models: bool = True


class RetrievalSearchRequest(BaseModel):
    query: str = ""
    species: str | None = None
    file_type: str | None = None
    category: str | None = None
    zone: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 10
    index_root: str | None = None
    prefer_real_models: bool = True


class ProjectChatRequest(BaseModel):
    question: str
    species: str | None = None
    file_type: str | None = None
    category: str | None = None
    zone: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    limit: int = 6
    index_root: str | None = None
    prefer_real_models: bool = True


class ChatSource(BaseModel):
    id: str
    title: str
    relative_path: str
    source_path: str
    file_name: str
    extension: str
    category: str
    species: str | None = None
    observed_at: str | None = None
    zone: str | None = None
    geometry_type: str | None = None
    score: float = 0.0
    snippet: str = ""


class ProjectChatResponse(BaseModel):
    project_id: str
    project_slug: str
    question: str
    answer: str
    backend: str
    index_path: str
    model_name: str
    total_candidates: int
    returned_hits: int
    citations: list[str] = Field(default_factory=list)
    sources: list[ChatSource] = Field(default_factory=list)
    created_at: datetime


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
