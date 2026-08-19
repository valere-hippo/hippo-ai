import logging
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .auth import create_access_token, get_current_user, verify_credentials
from .audit import write_audit
from .backups import create_project_backup
from .logging_config import configure_logging
from .models import (
    BackupResult,
    ChatSource,
    HealthResponse,
    LoginRequest,
    ProjectCreate,
    ProjectInventory,
    ProjectRecord,
    ProjectChatRequest,
    ProjectChatResponse,
    RetrievalIndexRequest,
    RetrievalSearchRequest,
    TokenResponse,
    UserContext,
)
from .project_store import ProjectStore
from .settings import get_settings
from tier_ai.chat import answer_project_question
from tier_ai.retrieval import RetrievalFilter, index_project, search_project, to_dict

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()
store = ProjectStore()

app = FastAPI(title=settings.app_name, version=settings.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.version,
        workspace_root=str(settings.data_root),
    )


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    if not verify_credentials(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(payload.username)
    write_audit("auth.login", "user", payload.username, payload.username, {"ip": "unknown"})
    return TokenResponse(access_token=token)


@app.get("/auth/me", response_model=UserContext)
def me(user: UserContext = Depends(get_current_user)) -> UserContext:
    return user


@app.get("/projects", response_model=list[ProjectRecord])
def list_projects(user: UserContext = Depends(get_current_user)) -> list[ProjectRecord]:
    logger.info("List projects requested by %s", user.username)
    return store.list_projects()


@app.post("/projects", response_model=ProjectRecord, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, user: UserContext = Depends(get_current_user)) -> ProjectRecord:
    project = store.create_project(payload)
    write_audit("project.create", "project", project.id, user.username, {"name": project.name, "slug": project.slug})
    return project


@app.get("/projects/{project_id}", response_model=ProjectRecord)
def get_project(project_id: str, user: UserContext = Depends(get_current_user)) -> ProjectRecord:
    logger.info("Project %s requested by %s", project_id, user.username)
    return store.get_project(project_id)


@app.post("/projects/{project_id}/backup", response_model=BackupResult)
def backup_project(project_id: str, user: UserContext = Depends(get_current_user)) -> BackupResult:
    project = store.get_project(project_id)
    backup = create_project_backup(project)
    write_audit(
        "project.backup",
        "project",
        project.id,
        user.username,
        {"archive_path": backup.archive_path, "size_bytes": backup.size_bytes},
    )
    return backup


@app.get("/projects/{project_id}/files")
def list_project_files(project_id: str, user: UserContext = Depends(get_current_user)) -> dict:
    project = store.get_project(project_id)
    root = Path(project.metadata.get("source_path") or project.root_path)
    files = [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()]
    return {"project_id": project.id, "files": files}


@app.get("/projects/{project_id}/inventory", response_model=ProjectInventory)
def get_project_inventory(project_id: str, user: UserContext = Depends(get_current_user)) -> ProjectInventory:
    project = store.get_project(project_id)
    logger.info("Project inventory requested by %s for %s", user.username, project_id)
    return store.get_project_inventory(project_id)


@app.post("/projects/{project_id}/inventory/refresh", response_model=ProjectInventory)
def refresh_project_inventory(project_id: str, user: UserContext = Depends(get_current_user)) -> ProjectInventory:
    logger.info("Project inventory refresh requested by %s for %s", user.username, project_id)
    inventory = store.refresh_project_inventory(project_id)
    write_audit("project.inventory.refresh", "project", project_id, user.username, {"record_count": inventory.summary.total_files})
    return inventory


@app.post("/projects/{project_id}/retrieval/index")
def index_project_retrieval(
    project_id: str,
    payload: RetrievalIndexRequest,
    user: UserContext = Depends(get_current_user),
) -> dict:
    project = store.get_project(project_id)
    source_root = Path(payload.source_root or project.metadata.get("source_path") or project.root_path)
    index_root = Path(payload.index_root or settings.state_dir / "retrieval")
    summary = index_project(
        project_id=project.id,
        project_slug=project.slug,
        source_root=source_root,
        index_root=index_root,
        use_qdrant=payload.use_qdrant,
        prefer_real_models=payload.prefer_real_models,
    )
    write_audit(
        "project.retrieval.index",
        "project",
        project.id,
        user.username,
        {"backend": summary.backend, "documents": summary.indexed_documents, "index_path": summary.index_path},
    )
    return to_dict(summary)


@app.post("/projects/{project_id}/retrieval/search")
def search_project_retrieval(
    project_id: str,
    payload: RetrievalSearchRequest,
    user: UserContext = Depends(get_current_user),
) -> dict:
    project = store.get_project(project_id)
    index_root = Path(payload.index_root or settings.state_dir / "retrieval")
    filters = RetrievalFilter(
        species=payload.species,
        file_type=payload.file_type,
        category=payload.category,
        zone=payload.zone,
        date_from=payload.date_from,
        date_to=payload.date_to,
        limit=payload.limit,
    )
    result = search_project(
        project_id=project.id,
        project_slug=project.slug,
        query=payload.query,
        index_root=index_root,
        filters=filters,
        prefer_real_models=payload.prefer_real_models,
    )
    write_audit(
        "project.retrieval.search",
        "project",
        project.id,
        user.username,
        {"query": payload.query, "hits": result.returned_hits, "backend": result.backend},
    )
    return to_dict(result)


@app.post("/projects/{project_id}/chat", response_model=ProjectChatResponse)
def chat_project(
    project_id: str,
    payload: ProjectChatRequest,
    user: UserContext = Depends(get_current_user),
) -> ProjectChatResponse:
    project = store.get_project(project_id)
    index_root = Path(payload.index_root or settings.state_dir / "retrieval")
    filters = RetrievalFilter(
        species=payload.species,
        file_type=payload.file_type,
        category=payload.category,
        zone=payload.zone,
        date_from=payload.date_from,
        date_to=payload.date_to,
        limit=payload.limit,
    )
    response = answer_project_question(
        project_id=project.id,
        project_slug=project.slug,
        question=payload.question,
        index_root=index_root,
        filters=filters,
        prefer_real_models=payload.prefer_real_models,
        max_sources=payload.limit,
    )
    write_audit(
        "project.chat",
        "project",
        project.id,
        user.username,
        {"question": payload.question, "hits": response.returned_hits, "backend": response.backend},
    )
    return ProjectChatResponse(
        project_id=response.project_id,
        project_slug=response.project_slug,
        question=response.question,
        answer=response.answer,
        backend=response.backend,
        index_path=response.index_path,
        model_name=response.model_name,
        total_candidates=response.total_candidates,
        returned_hits=response.returned_hits,
        citations=response.citations,
        sources=[
            ChatSource(
                id=source.id,
                title=source.title,
                relative_path=source.relative_path,
                source_path=source.source_path,
                file_name=source.file_name,
                extension=source.extension,
                category=source.category,
                species=source.species,
                observed_at=source.observed_at,
                zone=source.zone,
                geometry_type=source.geometry_type,
                score=source.score,
                snippet=source.snippet,
            )
            for source in response.sources
        ],
        created_at=datetime.fromisoformat(response.created_at),
    )
