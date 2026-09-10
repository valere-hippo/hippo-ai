from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from app.api.dependencies import DbSession, get_current_user
from app.models.chat import Conversation, ChatMessage
from app.models.tool import AITool
from app.schemas.tool import AIToolResponse

router = APIRouter(prefix="/tools", tags=["tools-library-fallback"])


def _clean_markdown_text(content: str) -> tuple[str, str | None, str | None]:
    text = (content or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Die Markdown-Datei ist leer.")

    title = None
    for line in text.splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            title = candidate
            break

    if not title:
        title = "Unbenanntes Tool"

    description = None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1:
        description = lines[1][:240]

    return text, title, description


@router.post("/library/upload", response_model=AIToolResponse, status_code=status.HTTP_201_CREATED)
async def upload_tool_markdown(db: DbSession, file: UploadFile = File(...), current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    if not (file.filename or "").lower().endswith(".md"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bitte eine Markdown-Datei (.md) hochladen.")

    raw = await file.read()
    text, title, description = _clean_markdown_text(raw.decode("utf-8", errors="ignore"))
    tool_name = title or Path(file.filename or "tool.md").stem.replace("_", " ").strip()

    existing = await db.execute(select(AITool).where(AITool.name == tool_name))
    tool = existing.scalar_one_or_none()
    if tool is not None:
        await db.execute(
            AITool.__table__.update()
            .where(AITool.id == tool.id)
            .values(
                description=description,
                instructions=text,
                is_enabled=True,
                updated_at=datetime.utcnow(),
            )
        )
        await db.commit()
        refreshed = await db.execute(select(AITool).where(AITool.id == tool.id))
        return refreshed.scalar_one()

    stmt = insert(AITool).values(
        name=tool_name,
        description=description,
        instructions=text,
        tool_type="workflow",
        arguments=None,
        working_directory=None,
        endpoint=None,
        method=None,
        platform=None,
        timeout_seconds=None,
        requires_confirmation=False,
        is_enabled=True,
    ).returning(AITool)
    try:
        result = await db.execute(stmt)
        await db.commit()
        return result.scalar_one()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ein Tool mit diesem Namen existiert bereits.")
