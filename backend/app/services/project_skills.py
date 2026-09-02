from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.models.skill import ProjectSkill


async def load_project_skills(db: Any, project_id: int, enabled_only: bool = False) -> list[ProjectSkill]:
    stmt = select(ProjectSkill).where(ProjectSkill.project_id == project_id)
    if enabled_only:
        stmt = stmt.where(ProjectSkill.is_enabled.is_(True))
    stmt = stmt.order_by(ProjectSkill.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


def format_project_skills_context(skills: list[ProjectSkill]) -> str:
    active_skills = [skill for skill in skills if getattr(skill, "is_enabled", False)]
    if not active_skills:
        return ""

    lines = [
        "Aktive Projektskills:",
        "Die folgenden Skills sind projektbezogene Arbeitsanweisungen. Befolge sie, wenn die Benutzerfrage passt.",
    ]

    for skill in active_skills:
        lines.append(f"- Skill: {skill.name}")
        description = (skill.description or "").strip()
        if description:
            lines.append(f"  Beschreibung: {description}")
        instructions = (skill.instructions or "").strip()
        if instructions:
            lines.append("  Anweisung:")
            for line in instructions.splitlines():
                line = line.strip()
                if line:
                    lines.append(f"    {line}")

    return "\n".join(lines)


async def build_project_skills_context(db: Any, project_id: int) -> str:
    skills = await load_project_skills(db, project_id, enabled_only=True)
    return format_project_skills_context(skills)
