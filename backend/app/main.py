import logging

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .auth import create_access_token, get_current_user, verify_credentials
from .audit import write_audit
from .backups import create_project_backup
from .logging_config import configure_logging
from .models import BackupResult, HealthResponse, LoginRequest, ProjectCreate, ProjectRecord, TokenResponse, UserContext
from .project_store import ProjectStore
from .settings import get_settings

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
    root = settings.projects_dir / project.slug
    files = [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()]
    return {"project_id": project.id, "files": files}

