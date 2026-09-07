from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text

from app.api.dependencies import DbSession, get_current_user
from app.core.config import settings
from app.models.chat import ChatMessage, Conversation
from app.models.permission import ProjectPermission
from app.models.project import Project
from app.models.skill import ProjectSkill
from app.models.user import User, UserRole

router = APIRouter(prefix="/admin/overview", tags=["admin-overview"])
EMBEDDINGS_TABLE = f"{settings.postgres_schema}.ai_embeddings"


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
    }

    try:
        embeddings_result = await db.execute(text(f"SELECT count(*) FROM {EMBEDDINGS_TABLE}"))
        counts["embeddings"] = int(embeddings_result.scalar_one() or 0)
    except Exception:
        counts["embeddings"] = 0

    recent_projects = await db.execute(select(Project).order_by(Project.created_at.desc()).limit(8))
    recent_skills = await db.execute(select(ProjectSkill).order_by(ProjectSkill.created_at.desc()).limit(8))

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
    }
