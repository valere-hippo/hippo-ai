from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.api.dependencies import DbSession, get_current_user
from app.models.chat import ChatMessage, Conversation
from app.models.permission import ProjectPermission
from app.models.project import Project
from app.models.skill import ProjectSkill
from app.models.tool import AITool
from app.models.model_registry import ModelRegistry
from app.models.user import User, UserRole

router = APIRouter(prefix="/admin/overview", tags=["admin-overview"])


@router.get("/")
async def admin_overview(db: DbSession, current_user=Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")

    counts = {
        "users": int(await db.scalar(select(func.count()).select_from(User)) or 0),
        "projects": int(await db.scalar(select(func.count()).select_from(Project)) or 0),
        "project_permissions": int(await db.scalar(select(func.count()).select_from(ProjectPermission)) or 0),
        "conversations": int(await db.scalar(select(func.count()).select_from(Conversation)) or 0),
        "messages": int(await db.scalar(select(func.count()).select_from(ChatMessage)) or 0),
        "shared_skills": int(
            await db.scalar(select(func.count()).select_from(ProjectSkill).where(ProjectSkill.project_id.is_(None))) or 0
        ),
        "project_skills": int(
            await db.scalar(select(func.count()).select_from(ProjectSkill).where(ProjectSkill.project_id.is_not(None))) or 0
        ),
        "shared_tools": int(await db.scalar(select(func.count()).select_from(AITool)) or 0),
        "model_registry": int(await db.scalar(select(func.count()).select_from(ModelRegistry)) or 0),
        "model_errors": int(
            await db.scalar(select(func.count()).select_from(ModelRegistry).where(ModelRegistry.status != "ok")) or 0
        ),
        "embeddings": 0,
    }

    recent_projects = await db.execute(select(Project).order_by(Project.created_at.desc()).limit(8))
    recent_skills = await db.execute(select(ProjectSkill).order_by(ProjectSkill.created_at.desc()).limit(8))
    recent_tools = await db.execute(select(AITool).order_by(AITool.created_at.desc()).limit(8))
    recent_models = await db.execute(select(ModelRegistry).order_by(ModelRegistry.last_seen_at.desc()).limit(8))

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "counts": counts,
        "recent_projects": [
            {
                "id": item.id,
                "name": item.name,
                "watched_folder": item.watched_folder,
                "created_at": item.created_at,
            }
            for item in recent_projects.scalars().all()
        ],
        "recent_skills": [
            {
                "id": item.id,
                "name": item.name,
                "project_id": item.project_id,
                "is_enabled": item.is_enabled,
                "created_at": item.created_at,
            }
            for item in recent_skills.scalars().all()
        ],
        "recent_tools": [
            {
                "id": item.id,
                "name": item.name,
                "tool_type": item.tool_type,
                "is_enabled": item.is_enabled,
                "created_at": item.created_at,
            }
            for item in recent_tools.scalars().all()
        ],
        "recent_models": [
            {
                "id": item.id,
                "provider": item.provider,
                "source_url": item.source_url,
                "capability": item.capability,
                "model_id": item.model_id,
                "display_name": item.display_name,
                "status": item.status,
                "context_window": item.context_window,
                "max_output_tokens": item.max_output_tokens,
                "last_seen_at": item.last_seen_at,
            }
            for item in recent_models.scalars().all()
        ],
    }
