from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from app.models.tool import AITool

_WORD_RE = re.compile(r"[\wÀ-ÿ]+", re.UNICODE)


def _normalize_tokens(text: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(text or "") if len(token) > 2}


def _tool_search_score(tool: AITool, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0

    name_tokens = _normalize_tokens(tool.name or "")
    description_tokens = _normalize_tokens(tool.description or "")
    instruction_tokens = _normalize_tokens(tool.instructions or "")

    score = 0.0
    if name_tokens:
        score += 5.0 * len(query_tokens & name_tokens)
    if description_tokens:
        score += 2.5 * len(query_tokens & description_tokens)
    if instruction_tokens:
        score += 1.0 * len(query_tokens & instruction_tokens)

    return score


async def load_shared_tools(db: Any, enabled_only: bool = False) -> list[AITool]:
    stmt = select(AITool)
    if enabled_only:
        stmt = stmt.where(AITool.is_enabled.is_(True))
    stmt = stmt.order_by(AITool.created_at.asc())
    result = await db.execute(stmt)
    return result.scalars().all()


def rank_tools_for_query(tools: list[AITool], query: str, limit: int = 5) -> list[AITool]:
    active_tools = [tool for tool in tools if getattr(tool, "is_enabled", False)]
    if not active_tools:
        return []

    query_tokens = _normalize_tokens(query)
    if not query_tokens:
        return active_tools[:limit]

    scored: list[tuple[float, int, AITool]] = []
    for index, tool in enumerate(active_tools):
        score = _tool_search_score(tool, query_tokens)
        scored.append((score, index, tool))

    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked = [tool for score, _, tool in scored if score > 0]
    if not ranked:
        ranked = active_tools
    return ranked[:limit]


def format_tools_context(tools: list[AITool], query: str | None = None, limit: int = 5) -> str:
    if not tools:
        return ""

    selected = rank_tools_for_query(tools, query or "", limit=limit) if query else [tool for tool in tools if getattr(tool, "is_enabled", False)][:limit]
    if not selected:
        return ""

    lines = [
        "Verfügbare Tools und ihre Schnittstellen:",
        "Nutze diese Tools nur, wenn sie zur aktuellen Anfrage passen. Bevorzuge das passendste Tool zuerst.",
    ]

    for tool in selected:
        lines.append(f"- {tool.name} [{tool.tool_type}]")
        description = (tool.description or "").strip()
        if description:
            lines.append(f"  Beschreibung: {description}")
        instructions = [line.strip() for line in (tool.instructions or "").splitlines() if line.strip()]
        if instructions:
            lines.append("  Vorgehen:")
            for line in instructions[:12]:
                lines.append(f"    {line}")
        if tool.command:
            lines.append(f"  Command: {tool.command}")
        if tool.endpoint:
            lines.append(f"  Endpoint: {tool.method or 'POST'} {tool.endpoint}")

    return "\n".join(lines)


async def build_tools_context(db: Any, query: str | None = None, limit: int = 5) -> str:
    tools = await load_shared_tools(db, enabled_only=True)
    return format_tools_context(tools, query=query, limit=limit)
