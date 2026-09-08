from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import insert, select

from app.api.dependencies import DbSession, get_current_user
from app.models.permission import PermissionLevel, ProjectPermission
from app.models.project import Project
from app.models.user import UserRole
from app.schemas.project import ProjectCreate, ProjectResponse
from app.services.notifications import notify_project_created
from app.services.project_storage import delete_project_bucket, ensure_project_bucket, has_s3_storage

router = APIRouter(prefix="/projects", tags=["projects"])


def _normalize_shared_folder(folder: str) -> str:
    path = Path(folder).expanduser()
    if not path.is_absolute():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bitte einen absoluten Ordnerpfad auswählen.")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Der angegebene Ordner existiert nicht.") from exc

    if not resolved.is_dir():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bitte einen gültigen Ordner auswählen.")

    return str(resolved)


async def _load_project(db: DbSession, project_id: int) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden.")
    return project


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, db: DbSession, current_user=Depends(get_current_user)):
    watched_folder = _normalize_shared_folder(payload.watched_folder)

    stmt = insert(Project).values(
        name=payload.name.strip(),
        description=payload.description,
        owner_id=current_user.id,
        watched_folder=watched_folder,
    ).returning(Project)

    result = await db.execute(stmt)
    await db.commit()
    project = result.scalar_one()

    if has_s3_storage():
        try:
            ensure_project_bucket(project)
        except Exception:
            # Shared-folder projects no longer depend on S3; keep the project if bucket setup fails.
            pass

    await db.execute(
        insert(ProjectPermission).values(user_id=current_user.id, project_id=project.id, level=PermissionLevel.ADMIN)
    )
    await db.commit()

    try:
        await notify_project_created(project, current_user)
    except Exception:
        pass

    return project


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(db: DbSession, current_user=Depends(get_current_user)):
    if current_user.role == UserRole.ADMIN:
        stmt = select(Project)
    else:
        stmt = select(Project).where(
            (Project.owner_id == current_user.id)
            | (
                Project.id.in_(
                    select(ProjectPermission.project_id).where(ProjectPermission.user_id == current_user.id)
                )
            )
        )

    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project(db, project_id)
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: int, payload: ProjectCreate, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project(db, project_id)
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")

    watched_folder = _normalize_shared_folder(payload.watched_folder)
    updates = {
        "name": payload.name.strip(),
        "description": payload.description,
        "watched_folder": watched_folder,
    }
    await db.execute(Project.__table__.update().where(Project.id == project_id).values(**updates))
    await db.commit()

    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one()


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project(db, project_id)
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")

    from app.models.chat import Conversation, ChatMessage
    from app.models.skill import ProjectSkill

    convs = await db.execute(select(Conversation.id).where(Conversation.project_id == project_id))
    conv_ids = [row[0] for row in convs.fetchall()]
    if conv_ids:
        await db.execute(ChatMessage.__table__.delete().where(ChatMessage.conversation_id.in_(conv_ids)))
        await db.execute(Conversation.__table__.delete().where(Conversation.id.in_(conv_ids)))

    await db.execute(ProjectSkill.__table__.delete().where(ProjectSkill.project_id == project_id))
    await db.execute(ProjectPermission.__table__.delete().where(ProjectPermission.project_id == project_id))
    await db.execute(Project.__table__.delete().where(Project.id == project_id))
    await db.commit()

    delete_project_bucket(project)
    return {"ok": True}
