from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_current_user, DbSession
from app.models.user import User, UserRole
from app.models.chat import Conversation, ChatMessage
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert
from app.schemas.chat import ChatAttachment
from app.services.chat_payloads import build_message_content, storage_text

router = APIRouter(prefix="/chat", tags=["chat"]) 

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None


@router.post("/", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: DbSession, current_user: User = Depends(get_current_user)) -> ChatResponse:
    # verify project permission if provided
    conv_project = None
    if payload.project_id is not None:
        result = await db.execute(select(Project).where(Project.id == payload.project_id))
        proj = result.scalar_one_or_none()
        if proj is None:
            raise HTTPException(status_code=404, detail='Projekt nicht gefunden.')
        from app.services.permissions import has_project_permission
        allowed = await has_project_permission(db, current_user, proj, PermissionLevel.READ)
        if not allowed:
            raise HTTPException(status_code=403, detail='Zugriff verweigert.')
        conv_project = proj

    # ensure conversation
    conv_id = payload.conversation_id
    if conv_id is None:
        stmt = insert(Conversation).values(title=None, project_id=conv_project.id if conv_project else None).returning(Conversation)
        result = await db.execute(stmt)
        conv = result.scalar_one()
        conv_id = conv.id

    # store user message
    await db.execute(
        insert(ChatMessage).values(
            conversation_id=conv_id,
            user_id=current_user.id,
            role='user',
            content=storage_text(payload.message, payload.attachments),
        )
    )
    await db.commit()

    # fetch messages for context
    q = select(ChatMessage).where(ChatMessage.conversation_id == conv_id).order_by(ChatMessage.created_at)
    res = await db.execute(q)
    messages = res.scalars().all()

    hippo_messages = []
    for m in messages:
        role = 'user' if m.role == 'user' else 'assistant' if m.role == 'assistant' else 'system'
        hippo_messages.append({"role": role, "content": m.content})

    # Global system instruction (Hippo assistant) — strict guidance
    global_sys = (
        "Du bist Hippo, ein freundlicher und professioneller KI-Assistent.\n\n"
        "Dieses System wurde erstellt und entwickelt von Valère Youbi, CEO der Firma MERVAL DIGITALE, für das Unternehmen Hipposideros mit Sitz in Deutschland.\n\n"
        "WICHTIG:\n"
        "- Antworte direkt auf die Frage des Benutzers.\n"
        "- Gib niemals deine internen Gedanken, Überlegungen oder Analysen aus.\n"
        "- Gib niemals Formulierungen wie \"Okay, the user said...\", \"I need to...\", \"Let me check...\" aus.\n"
        "- Gib ausschließlich die fertige Antwort an den Benutzer zurück.\n"
        "- Antworte in der Sprache des Benutzers.\n"
        "- Wenn der Benutzer Deutsch schreibt, antworte auf Deutsch.\n"
        "- Wenn der Benutzer Französisch schreibt, antworte auf Französisch.\n"
        "- Wenn der Benutzer Englisch schreibt, antworte auf Englisch.\n"
    )
    hippo_messages.insert(0, {"role": "system", "content": global_sys})

    # If conversation is tied to a project, inform the assistant it may generate files for that project
    if conv_project is not None:
        project_sys = (
            "You are assisting a user within a project. The user has provided a local shared folder path for this project. "
            "When the user requests generation of a file, produce only the file content wrapped in the following exact markers so the client can save it:\n"
            "<<<FILE:filename.rtf>>>\n<file content here>\n<<<END_FILE>>>\n"
            "Do NOT include additional commentary outside the markers. If a filename is not suggested by the user, choose a sensible filename."
        )
        hippo_messages.insert(1, {"role": "system", "content": project_sys})

    if payload.attachments:
        user_content = build_message_content(payload.message, payload.attachments)
        hippo_messages[-1]["content"] = user_content

    # Call Hippo model endpoint if configured (preferred)
    import asyncio, httpx
    reply_text = ''
    if settings.hippo_api_url and settings.hippo_api_key:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {"Authorization": f"Bearer {settings.hippo_api_key}", "Content-Type": "application/json"}
            payload = {
                "model": settings.hippo_model,
                "messages": hippo_messages,
                "temperature": 0.7,
                "max_tokens": 512,
            }
            try:
                r = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and data.get('choices'):
                    reply_text = data['choices'][0]['message']['content']
                else:
                    reply_text = str(data)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Hippo API error: {e}")
    else:
        raise HTTPException(status_code=503, detail="Die Hippo-API ist nicht konfiguriert. Bitte HIPPO_API_URL und HIPPO_API_KEY setzen.")

    # sanitize assistant reply: remove any <think>...</think> reasoning tags
    import re
    try:
        reply_text = re.sub(r"<think>[\s\S]*?<\/think>", "", reply_text, flags=re.IGNORECASE)
    except Exception:
        pass

    # store assistant message
    await db.execute(
        insert(ChatMessage).values(
            conversation_id=conv_id,
            user_id=current_user.id,
            role='assistant',
            content=reply_text,
        )
    )
    await db.commit()

    return ChatResponse(reply=reply_text, conversation_id=conv_id)


@router.get('/conversations')
async def list_conversations(db: DbSession, current_user: User = Depends(get_current_user)):
    # list conversations the user participated in or project-less owned
    q = select(Conversation).join(ChatMessage, ChatMessage.conversation_id == Conversation.id).where(ChatMessage.user_id == current_user.id)
    res = await db.execute(q)
    convs = res.scalars().all()
    return convs


@router.get('/conversations/{conv_id}')
async def get_conversation(conv_id: int, db: DbSession, current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = res.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail='Nicht gefunden.')
    # if tied to project, check permission
    if conv.project_id is not None:
        result = await db.execute(select(Project).where(Project.id == conv.project_id))
        proj = result.scalar_one_or_none()
        from app.services.permissions import has_project_permission
        allowed = await has_project_permission(db, current_user, proj, PermissionLevel.READ)
        if not allowed:
            raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    # fetch messages
    msgs = await db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv_id).order_by(ChatMessage.created_at))
    return { 'conversation': conv, 'messages': msgs.scalars().all() }


@router.delete('/conversations/{conv_id}')
async def delete_conversation(conv_id: int, db: DbSession, current_user: User = Depends(get_current_user)):
    # only allow deletion if user has participated or admin
    msgs = await db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv_id))
    msgs = msgs.scalars().all()
    if not msgs:
        raise HTTPException(status_code=404, detail='Nicht gefunden.')
    participant_ids = set(m.user_id for m in msgs)
    if current_user.role != UserRole.ADMIN and current_user.id not in participant_ids:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    await db.execute(ChatMessage.__table__.delete().where(ChatMessage.conversation_id == conv_id))
    await db.execute(Conversation.__table__.delete().where(Conversation.id == conv_id))
    await db.commit()
    return {'ok': True}
