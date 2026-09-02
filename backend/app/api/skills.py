from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import DbSession, get_current_user
from app.models.permission import PermissionLevel
from app.models.project import Project
from app.models.skill import ProjectSkill
from app.schemas.skill import ProjectSkillCreate, ProjectSkillResponse, ProjectSkillUpdate

router = APIRouter(prefix="/projects/{project_id}/skills", tags=["skills"])


async def _load_project(db: DbSession, project_id: int) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden.")
    return project


async def _require_permission(db: DbSession, user, project: Project, level: PermissionLevel):
    from app.services.permissions import has_project_permission

    allowed = await has_project_permission(db, user, project, level)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")


@router.get("/", response_model=list[ProjectSkillResponse])
async def list_project_skills(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project(db, project_id)
    await _require_permission(db, current_user, project, PermissionLevel.READ)

    result = await db.execute(
        select(ProjectSkill)
        .where(ProjectSkill.project_id == project_id)
        .order_by(ProjectSkill.created_at.asc())
    )
    return result.scalars().all()


@router.post("/", response_model=ProjectSkillResponse, status_code=status.HTTP_201_CREATED)
async def create_project_skill(project_id: int, payload: ProjectSkillCreate, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project(db, project_id)
    await _require_permission(db, current_user, project, PermissionLevel.ADMIN)

    stmt = insert(ProjectSkill).values(
        project_id=project_id,
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        instructions=payload.instructions.strip(),
        is_enabled=payload.is_enabled,
    ).returning(ProjectSkill)
    try:
        result = await db.execute(stmt)
        await db.commit()
        return result.scalar_one()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Eine Skill mit diesem Namen existiert bereits.")


@router.patch("/{skill_id}", response_model=ProjectSkillResponse)
async def update_project_skill(project_id: int, skill_id: int, payload: ProjectSkillUpdate, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project(db, project_id)
    await _require_permission(db, current_user, project, PermissionLevel.ADMIN)

    result = await db.execute(
        select(ProjectSkill).where(ProjectSkill.id == skill_id, ProjectSkill.project_id == project_id)
    )
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill nicht gefunden.")

    updates: dict[str, object] = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.description is not None:
        updates["description"] = payload.description.strip()
    if payload.instructions is not None:
        updates["instructions"] = payload.instructions.strip()
    if payload.is_enabled is not None:
        updates["is_enabled"] = payload.is_enabled

    try:
        await db.execute(
            ProjectSkill.__table__.update().where(ProjectSkill.id == skill_id).values(**updates, updated_at=datetime.utcnow())
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Eine Skill mit diesem Namen existiert bereits.")

    result = await db.execute(select(ProjectSkill).where(ProjectSkill.id == skill_id))
    return result.scalar_one()


@router.delete("/{skill_id}")
async def delete_project_skill(project_id: int, skill_id: int, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project(db, project_id)
    await _require_permission(db, current_user, project, PermissionLevel.ADMIN)

    result = await db.execute(
        delete(ProjectSkill).where(ProjectSkill.id == skill_id, ProjectSkill.project_id == project_id)
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill nicht gefunden.")
    return {"ok": True}
