from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import DbSession, get_current_user
from app.models.chat_profile import ChatProfile
from app.models.project import Project
from app.models.user import UserRole
from app.schemas.chat_profile import ChatProfileCreate, ChatProfileResponse, ChatProfileUpdate
from app.services.chat_profiles import load_chat_profile, load_chat_profiles

router = APIRouter(prefix="/profiles", tags=["chat-profiles"])


async def _load_project(db: DbSession, project_id: int) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden.")
    return project


async def _load_profile_or_404(db: DbSession, profile_id: int) -> ChatProfile:
    profile = await load_chat_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profil nicht gefunden.")
    return profile


async def _assert_profile_permission(current_user, profile: ChatProfile, project: Project | None = None) -> None:
    if current_user.role == UserRole.ADMIN:
        return
    if profile.owner_id == current_user.id:
        return
    if project is not None and project.owner_id == current_user.id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")


@router.get("/", response_model=list[ChatProfileResponse])
async def list_profiles(db: DbSession, project_id: int | None = None, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    profiles = await load_chat_profiles(db, project_id=project_id, user_id=int(current_user.id), enabled_only=False)
    if project_id is not None:
        project = await _load_project(db, project_id)
        visible = []
        for profile in profiles:
            if (
                profile.project_id == project_id
                or profile.share_scope == 'shared'
                or profile.owner_id == current_user.id
                or current_user.role == UserRole.ADMIN
                or project.owner_id == current_user.id
            ):
                visible.append(profile)
        return visible
    return [
        profile
        for profile in profiles
        if profile.share_scope == 'shared' or profile.owner_id == current_user.id or current_user.role == UserRole.ADMIN
    ]


@router.post("/", response_model=ChatProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(payload: ChatProfileCreate, db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    if payload.project_id is not None:
        project = await _load_project(db, payload.project_id)
        await _assert_profile_permission(current_user, ChatProfile(owner_id=current_user.id, project_id=project.id, name=payload.name, chat_bot_id=payload.chat_bot_id), project)

    memory_namespace = payload.memory_namespace or f"profile-{payload.chat_bot_id.strip().lower().replace(' ', '-') }"
    stmt = insert(ChatProfile).values(
        owner_id=current_user.id,
        project_id=payload.project_id,
        name=payload.name.strip(),
        chat_bot_id=payload.chat_bot_id.strip(),
        description=payload.description.strip() if payload.description else None,
        memory_notes=payload.memory_notes.strip() if payload.memory_notes else None,
        system_prompt=payload.system_prompt.strip() if payload.system_prompt else None,
        memory_namespace=memory_namespace,
        share_scope=(payload.share_scope or ("project" if payload.project_id else "shared")).strip().lower(),
        model_provider=payload.model_provider.strip().lower() if payload.model_provider else None,
        model_name=payload.model_name.strip() if payload.model_name else None,
        allow_shared_skills=payload.allow_shared_skills,
        allow_shared_tools=payload.allow_shared_tools,
        is_active=payload.is_active,
    ).returning(ChatProfile)
    try:
        result = await db.execute(stmt)
        await db.commit()
        return result.scalar_one()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ein Profil mit dieser Bot-ID existiert bereits.")


@router.patch("/{profile_id}", response_model=ChatProfileResponse)
async def update_profile(profile_id: int, payload: ChatProfileUpdate, db: DbSession, current_user=Depends(get_current_user)):
    profile = await _load_profile_or_404(db, profile_id)
    project = await _load_project(db, profile.project_id) if profile.project_id else None
    await _assert_profile_permission(current_user, profile, project)

    updates: dict[str, object] = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.chat_bot_id is not None:
        updates["chat_bot_id"] = payload.chat_bot_id.strip()
    if payload.description is not None:
        updates["description"] = payload.description.strip()
    if payload.memory_notes is not None:
        updates["memory_notes"] = payload.memory_notes.strip()
    if payload.system_prompt is not None:
        updates["system_prompt"] = payload.system_prompt.strip()
    if payload.memory_namespace is not None:
        updates["memory_namespace"] = payload.memory_namespace.strip()
    if payload.share_scope is not None:
        updates["share_scope"] = payload.share_scope.strip().lower()
    if payload.model_provider is not None:
        updates["model_provider"] = payload.model_provider.strip().lower()
    if payload.model_name is not None:
        updates["model_name"] = payload.model_name.strip()
    if payload.allow_shared_skills is not None:
        updates["allow_shared_skills"] = payload.allow_shared_skills
    if payload.allow_shared_tools is not None:
        updates["allow_shared_tools"] = payload.allow_shared_tools
    if payload.is_active is not None:
        updates["is_active"] = payload.is_active
    await db.execute(ChatProfile.__table__.update().where(ChatProfile.id == profile.id).values(**updates, updated_at=datetime.utcnow()))
    await db.commit()
    refreshed = await db.execute(select(ChatProfile).where(ChatProfile.id == profile.id))
    return refreshed.scalar_one()


@router.delete("/{profile_id}")
async def delete_profile(profile_id: int, db: DbSession, current_user=Depends(get_current_user)):
    profile = await _load_profile_or_404(db, profile_id)
    project = await _load_project(db, profile.project_id) if profile.project_id else None
    await _assert_profile_permission(current_user, profile, project)
    result = await db.execute(delete(ChatProfile).where(ChatProfile.id == profile_id))
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profil nicht gefunden.")
    return {"ok": True}
