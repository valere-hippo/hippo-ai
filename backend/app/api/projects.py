from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import DbSession, get_current_user
from app.models.project import Project
from app.models.user import UserRole
from app.schemas.project import ProjectCreate, ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreate, db: DbSession, current_user=Depends(get_current_user)):
    # any authenticated user can create a project
    stmt = insert(Project).values(
        name=payload.name.strip(),
        description=payload.description,
        owner_id=current_user.id,
        watched_folder=payload.watched_folder,
    ).returning(Project)

    result = await db.execute(stmt)
    await db.commit()
    project = result.scalar_one()

    # grant owner ADMIN permission explicitly
    from app.models.permission import ProjectPermission, PermissionLevel
    await db.execute(
        insert(ProjectPermission).values(user_id=current_user.id, project_id=project.id, level=PermissionLevel.ADMIN)
    )
    await db.commit()

    return project


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(db: DbSession, current_user=Depends(get_current_user)):
    # Admins see all
    if current_user.role == UserRole.ADMIN:
        stmt = select(Project)
    else:
        # projects owned or with explicit permissions
        from app.models.permission import ProjectPermission
        stmt = select(Project).where(
            (Project.owner_id == current_user.id) |
            (Project.id.in_(
                select(ProjectPermission.project_id).where(ProjectPermission.user_id == current_user.id)
            ))
        )

    result = await db.execute(stmt)
    projects = result.scalars().all()
    return projects


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden.")
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: int, payload: ProjectCreate, db: DbSession, current_user=Depends(get_current_user)):
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden.")
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")
    # apply updates
    upd = {}
    if payload.name:
        upd['name'] = payload.name.strip()
    upd['description'] = payload.description
    upd['watched_folder'] = payload.watched_folder
    await db.execute(
        Project.__table__.update().where(Project.id == project_id).values(**upd)
    )
    await db.commit()
    res = await db.execute(select(Project).where(Project.id == project_id))
    return res.scalar_one()


@router.delete("/{project_id}")
async def delete_project(project_id: int, db: DbSession, current_user=Depends(get_current_user)):
    stmt = select(Project).where(Project.id == project_id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden.")
    if current_user.role != UserRole.ADMIN and project.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")
    # delete related permissions, conversations, messages first to avoid FK violations
    from app.models.permission import ProjectPermission
    from app.models.chat import Conversation, ChatMessage

    # delete messages for conversations tied to this project
    convs = await db.execute(select(Conversation.id).where(Conversation.project_id == project_id))
    conv_ids = [c[0] for c in convs.fetchall()]
    if conv_ids:
        await db.execute(ChatMessage.__table__.delete().where(ChatMessage.conversation_id.in_(conv_ids)))
        await db.execute(Conversation.__table__.delete().where(Conversation.id.in_(conv_ids)))
    # delete project permissions
    await db.execute(ProjectPermission.__table__.delete().where(ProjectPermission.project_id == project_id))
    # finally delete project
    await db.execute(Project.__table__.delete().where(Project.id == project_id))
    await db.commit()
    return {"ok": True}
