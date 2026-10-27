from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.models.chat_profile import ChatProfile


async def load_chat_profiles(db: Any, project_id: int | None = None, user_id: int | None = None, enabled_only: bool = False) -> list[ChatProfile]:
    stmt = select(ChatProfile)
    if project_id is not None:
        stmt = stmt.where((ChatProfile.project_id == project_id) | (ChatProfile.project_id.is_(None)))
    elif user_id is not None:
        stmt = stmt.where((ChatProfile.owner_id == user_id) | (ChatProfile.project_id.is_(None)))
    else:
        stmt = stmt.where(ChatProfile.project_id.is_(None))
    if enabled_only:
        stmt = stmt.where(ChatProfile.is_active.is_(True))
    stmt = stmt.order_by(ChatProfile.project_id.is_(None).desc(), ChatProfile.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def load_chat_profile(db: Any, profile_id: int) -> ChatProfile | None:
    result = await db.execute(select(ChatProfile).where(ChatProfile.id == profile_id))
    return result.scalar_one_or_none()


def build_chat_profile_context(profile: ChatProfile | None, project_name: str | None = None) -> str:
    if profile is None:
        return ""

    lines = [
        "Aktives Chat-Profil:",
        f"- Name: {profile.name}",
        f"- Bot-ID: {profile.chat_bot_id}",
    ]
    if project_name:
        lines.append(f"- Projekt: {project_name}")
    if profile.description:
        lines.append(f"- Beschreibung: {profile.description}")
    if profile.memory_notes:
        lines.append("- Profil-Memory:")
        lines.extend([f"  {line}" for line in profile.memory_notes.splitlines() if line.strip()])
    if profile.memory_namespace:
        lines.append(f"- Memory-Namespace: {profile.memory_namespace}")
    lines.append(f"- Freigabe: {getattr(profile, 'share_scope', 'private')}")
    if profile.model_provider or profile.model_name:
        lines.append(f"- Modell: {(profile.model_provider or 'default').strip()} / {(profile.model_name or 'default').strip()}")
    lines.append(f"- Geteilte Skills: {'ja' if profile.allow_shared_skills else 'nein'}")
    lines.append(f"- Geteilte Tools: {'ja' if profile.allow_shared_tools else 'nein'}")
    if profile.system_prompt:
        lines.append("- Eigener Systemprompt:")
        lines.extend([f"  {line}" for line in profile.system_prompt.splitlines() if line.strip()])
    return "\n".join(lines)


def build_profile_system_prompt(profile: ChatProfile | None) -> str:
    if profile is None:
        return ""

    parts = [
        f"Aktives Profil: {profile.name} (Bot-ID: {profile.chat_bot_id}).",
        "Behalte den Profilkontext konsistent über die Unterhaltung hinweg.",
    ]
    if profile.memory_namespace:
        parts.append(f"Nutze den Memory-Namespace {profile.memory_namespace} für dieses Profil.")
    parts.append(f"Freigabe-Scope des Profils: {getattr(profile, 'share_scope', 'private')}.")
    if profile.memory_notes:
        parts.append("Gedächtnis des Profils:")
        parts.append(profile.memory_notes.strip())
    if profile.system_prompt:
        parts.append(profile.system_prompt.strip())
    return "\n".join(parts)
