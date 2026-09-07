from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from app.models.skill import ProjectSkill


_WORD_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


def _normalize_tokens(text: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(text or "") if len(token) > 2}


def _skill_search_score(skill: ProjectSkill, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0

    name_tokens = _normalize_tokens(skill.name or "")
    description_tokens = _normalize_tokens(skill.description or "")
    instruction_tokens = _normalize_tokens(skill.instructions or "")

    score = 0.0
    if name_tokens:
        score += 5.0 * len(query_tokens & name_tokens)
    if description_tokens:
        score += 2.5 * len(query_tokens & description_tokens)
    if instruction_tokens:
        score += 1.0 * len(query_tokens & instruction_tokens)

    return score


async def load_project_skills(db: Any, project_id: int, enabled_only: bool = False) -> list[ProjectSkill]:
    stmt = select(ProjectSkill).where(
        (ProjectSkill.project_id == project_id) | (ProjectSkill.project_id.is_(None))
    )
    if enabled_only:
        stmt = stmt.where(ProjectSkill.is_enabled.is_(True))
    stmt = stmt.order_by(ProjectSkill.project_id.is_(None).desc(), ProjectSkill.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


def rank_project_skills_for_query(skills: list[ProjectSkill], query: str, limit: int = 5) -> list[ProjectSkill]:
    active_skills = [skill for skill in skills if getattr(skill, "is_enabled", False)]
    if not active_skills:
        return []

    query_tokens = _normalize_tokens(query)
    if not query_tokens:
        return active_skills[:limit]

    scored: list[tuple[float, int, ProjectSkill]] = []
    for index, skill in enumerate(active_skills):
        score = _skill_search_score(skill, query_tokens)
        scope_bonus = 0.25 if getattr(skill, "project_id", None) is not None else 0.0
        scored.append((score + scope_bonus, index, skill))

    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked = [skill for score, _, skill in scored if score > 0]
    if not ranked:
        ranked = active_skills
    return ranked[:limit]


def format_project_skills_context(skills: list[ProjectSkill], query: str | None = None, limit: int = 5) -> str:
    if not skills:
        return ""

    selected = rank_project_skills_for_query(skills, query or "", limit=limit) if query else [skill for skill in skills if getattr(skill, "is_enabled", False)][:limit]
    if not selected:
        return ""

    lines = [
        "Relevante Skills und Arbeitsanweisungen:",
        "Nutze diese Hinweise nur, wenn sie zur aktuellen Anfrage passen. Befolge die Anweisung des passendsten Skills zuerst.",
    ]

    for skill in selected:
        scope = "Geteilt" if getattr(skill, "project_id", None) is None else f"Projekt {skill.project_id}"
        lines.append(f"- {skill.name} [{scope}]")
        description = (skill.description or "").strip()
        if description:
            lines.append(f"  Kurzbeschreibung: {description}")
        instructions = [line.strip() for line in (skill.instructions or "").splitlines() if line.strip()]
        if instructions:
            lines.append("  Anweisung:")
            for line in instructions[:12]:
                lines.append(f"    {line}")

    return "\n".join(lines)


async def load_shared_skills(db: Any, enabled_only: bool = False) -> list[ProjectSkill]:
    stmt = select(ProjectSkill).where(ProjectSkill.project_id.is_(None))
    if enabled_only:
        stmt = stmt.where(ProjectSkill.is_enabled.is_(True))
    stmt = stmt.order_by(ProjectSkill.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def build_shared_skills_context(db: Any, query: str | None = None, limit: int = 5) -> str:
    skills = await load_shared_skills(db, enabled_only=True)
    return format_project_skills_context(skills, query=query, limit=limit)


async def build_project_skills_context(db: Any, project_id: int, query: str | None = None, limit: int = 5) -> str:
    skills = await load_project_skills(db, project_id, enabled_only=True)
    return format_project_skills_context(skills, query=query, limit=limit)
