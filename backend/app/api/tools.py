from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, insert, select

from sqlalchemy.exc import IntegrityError

from app.api.dependencies import DbSession, get_current_user
from app.models.chat import Conversation, ChatMessage
from app.models.tool import AITool
from app.models.user import User
from app.schemas.tool import AIToolCreate, AIToolResponse, AIToolUpdate

router = APIRouter(prefix="/tools", tags=["tools"])
library_router = APIRouter(prefix="/tools", tags=["tools-library"])


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


def _parse_json_dict(value: object) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            import json
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


async def _load_tool(db: DbSession, tool_id: int) -> AITool:
    result = await db.execute(select(AITool).where(AITool.id == tool_id))
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool nicht gefunden.")
    return tool


@library_router.get("/library", response_model=list[AIToolResponse])
async def list_tools(db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    result = await db.execute(select(AITool).order_by(AITool.created_at.asc()))
    return result.scalars().all()


@library_router.post("/library", response_model=AIToolResponse, status_code=status.HTTP_201_CREATED)
async def create_tool(payload: AIToolCreate, db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    stmt = insert(AITool).values(
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        instructions=payload.instructions.strip(),
        tool_type=payload.tool_type.strip(),
        command=payload.command.strip() if payload.command else None,
        arguments=payload.arguments.strip() if payload.arguments else None,
        working_directory=payload.working_directory.strip() if payload.working_directory else None,
        endpoint=payload.endpoint.strip() if payload.endpoint else None,
        method=payload.method.strip().upper() if payload.method else None,
        platform=payload.platform.strip().lower() if payload.platform else None,
        timeout_seconds=payload.timeout_seconds,
        requires_confirmation=payload.requires_confirmation,
        parameters=payload.parameters or {},
        is_enabled=payload.is_enabled,
    ).returning(AITool)
    try:
        result = await db.execute(stmt)
        await db.commit()
        return result.scalar_one()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ein Tool mit diesem Namen existiert bereits.")


@library_router.post("/library/upload", response_model=AIToolResponse, status_code=status.HTTP_201_CREATED)
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
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one()


@library_router.patch("/library/{tool_id}", response_model=AIToolResponse)
async def update_tool(tool_id: int, payload: AIToolUpdate, db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    tool = await _load_tool(db, tool_id)
    updates: dict[str, object] = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.description is not None:
        updates["description"] = payload.description.strip()
    if payload.instructions is not None:
        updates["instructions"] = payload.instructions.strip()
    if payload.tool_type is not None:
        updates["tool_type"] = payload.tool_type.strip()
    if payload.command is not None:
        updates["command"] = payload.command.strip()
    if payload.arguments is not None:
        updates["arguments"] = payload.arguments.strip()
    if payload.working_directory is not None:
        updates["working_directory"] = payload.working_directory.strip()
    if payload.endpoint is not None:
        updates["endpoint"] = payload.endpoint.strip()
    if payload.method is not None:
        updates["method"] = payload.method.strip().upper()
    if payload.platform is not None:
        updates["platform"] = payload.platform.strip().lower()
    if payload.timeout_seconds is not None:
        updates["timeout_seconds"] = payload.timeout_seconds
    if payload.requires_confirmation is not None:
        updates["requires_confirmation"] = payload.requires_confirmation
    if payload.parameters is not None:
        updates["parameters"] = payload.parameters
    if payload.is_enabled is not None:
        updates["is_enabled"] = payload.is_enabled

    try:
        await db.execute(AITool.__table__.update().where(AITool.id == tool.id).values(**updates, updated_at=datetime.utcnow()))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ein Tool mit diesem Namen existiert bereits.")

    result = await db.execute(select(AITool).where(AITool.id == tool.id))
    return result.scalar_one()


@library_router.delete("/library/{tool_id}")
async def delete_tool(tool_id: int, db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    result = await db.execute(delete(AITool).where(AITool.id == tool_id))
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool nicht gefunden.")
    return {"ok": True}


@library_router.post("/library/from-chat", response_model=AIToolResponse, status_code=status.HTTP_201_CREATED)
async def create_tool_from_chat(payload: dict, db: DbSession, current_user=Depends(get_current_user)):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")

    conversation_id = int(payload.get("conversation_id") or 0)
    if conversation_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="conversation_id fehlt.")

    conv_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = conv_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konversation nicht gefunden.")

    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = msg_result.scalars().all()
    transcript_lines = []
    last_user_message = None
    for message in messages:
        content = (message.content or "").strip()
        if not content:
            continue
        transcript_lines.append(f"{message.role.upper()}: {content}")
        if message.role == "user":
            last_user_message = content

    name = str(payload.get("name") or "").strip() or (conversation.title or "").strip() or (last_user_message or "Unbenanntes Tool").splitlines()[0][:120]
    description = str(payload.get("description") or "").strip() or ((last_user_message or "").strip()[:240] or None)
    instructions = str(payload.get("instructions") or "").strip() or "\n\n".join([
        "Aus dem Chat abgeleitetes Tool.",
        f"Konversation: {conversation.title or f'#{conversation.id}'}",
        "Transkript:",
        "\n".join(transcript_lines) if transcript_lines else "(keine Nachrichten gefunden)",
    ])

    def _maybe_int(value):
        try:
            return int(value) if value not in (None, "") else None
        except Exception:
            return None

    parameters = payload.get("parameters")
    if isinstance(parameters, str):
        import json
        try:
            parameters = json.loads(parameters)
        except Exception:
            parameters = None

    stmt = insert(AITool).values(
        name=name,
        description=description,
        instructions=instructions,
        tool_type=str(payload.get("tool_type") or "workflow").strip() or "workflow",
        arguments=str(payload.get("arguments") or "").strip() or None,
        working_directory=str(payload.get("working_directory") or "").strip() or None,
        endpoint=str(payload.get("endpoint") or "").strip() or None,
        method=(str(payload.get("method") or "").strip().upper() or None),
        platform=(str(payload.get("platform") or "").strip().lower() or None),
        timeout_seconds=_maybe_int(payload.get("timeout_seconds")),
        requires_confirmation=bool(payload.get("requires_confirmation")),
        parameters=parameters or {},
        is_enabled=bool(payload.get("is_enabled", True)),
    ).returning(AITool)
    try:
        result = await db.execute(stmt)
        await db.commit()
        return result.scalar_one()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ein Tool mit diesem Namen existiert bereits.")
