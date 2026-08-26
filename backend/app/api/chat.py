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
from app.services.chat_payloads import build_message_content, derive_conversation_title, storage_text
from app.services.generated_files import extract_generated_files, save_generated_file

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

    conv_title = derive_conversation_title(payload.message, payload.attachments)
    await db.execute(
        Conversation.__table__.update()
        .where(Conversation.id == conv_id)
        .where(Conversation.title.is_(None))
        .values(title=conv_title)
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
        "Hippo AI wurde im August 2026 von Valère Youbi, CEO der MERVAL DIGITALE, für HIPPOSIDEROS entwickelt.\n"
        "Hippo AI gehört zu HIPPOSIDEROS.\n\n"
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
            "You are assisting a user within a project. The project has a shared folder path where generated files can be saved.\n"
            "When the user asks for a document, generate one of these file types:\n"
            "- Word documents: use .docx\n"
            "- PDF documents: use .pdf\n"
            "- Images: use .png, .jpg, or .jpeg\n"
            "- Vector images: use .svg\n"
            "Return only the file payload wrapped in exact markers and no extra commentary.\n"
            "Use this format:\n"
            "<<<FILE:filename.ext>>>\n"
            "<file content here>\n"
            "<<<END_FILE>>>\n"
            "For .docx and .pdf, provide the final document text/content. For .svg, provide valid SVG markup. For raster images (.png/.jpg/.jpeg), provide a concise visual description or poster brief that should be rendered into the image.\n"
            "If the user asks to analyze documents from the shared folder, use the project context and answer in the user's language."
        )
        hippo_messages.insert(1, {"role": "system", "content": project_sys})

    fallback_messages = [dict(item) for item in hippo_messages]
    if payload.attachments:
        hippo_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=True)
        fallback_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=False)

    # Call Hippo model endpoint if configured (preferred)
    import asyncio, httpx
    reply_text = ''
    if settings.hippo_api_url and settings.hippo_api_key:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {"Authorization": f"Bearer {settings.hippo_api_key}", "Content-Type": "application/json"}
            model_payload = {
                "model": settings.hippo_model,
                "messages": hippo_messages,
                "temperature": 0.7,
                "max_tokens": 512,
            }
            try:
                r = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=model_payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and data.get('choices'):
                    reply_text = data['choices'][0]['message']['content']
                else:
                    reply_text = str(data)
            except httpx.HTTPStatusError as e:
                if payload.attachments and e.response is not None and e.response.status_code == 400:
                    retry_payload = {
                        "model": settings.hippo_model,
                        "messages": fallback_messages,
                        "temperature": 0.7,
                        "max_tokens": 512,
                    }
                    retry = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=retry_payload, headers=headers)
                    retry.raise_for_status()
                    data = retry.json()
                    if isinstance(data, dict) and data.get('choices'):
                        reply_text = data['choices'][0]['message']['content']
                    else:
                        reply_text = str(data)
                else:
                    raise
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

    generated_files, cleaned_reply = extract_generated_files(reply_text)
    project_folder = conv_project.watched_folder if conv_project else None
    saved_paths: list[str] = []
    if generated_files and project_folder:
        for file in generated_files:
            saved_paths.append(save_generated_file(project_folder, file.filename, file.content))
        if saved_paths:
            save_note = "Datei gespeichert: " + ", ".join(saved_paths)
            reply_text = f"{cleaned_reply}\n\n{save_note}".strip() if cleaned_reply else save_note
    elif generated_files:
        reply_text = (
            f"{cleaned_reply}\n\nIch habe den Entwurf erstellt, aber diesem Chat ist kein gemeinsamer Ordner zugeordnet."
            if cleaned_reply
            else "Ich habe den Entwurf erstellt, aber diesem Chat ist kein gemeinsamer Ordner zugeordnet."
        )
    elif cleaned_reply:
        reply_text = cleaned_reply

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
    q = (
        select(Conversation)
        .where(
            Conversation.id.in_(
                select(ChatMessage.conversation_id)
                .where(ChatMessage.user_id == current_user.id)
                .distinct()
            )
        )
        .order_by(Conversation.created_at.desc())
    )
    res = await db.execute(q)
    convs = res.scalars().all()
    result = []
    for conv in convs:
        title = conv.title
        if not title:
            first_msg = await db.execute(
                select(ChatMessage.content)
                .where(ChatMessage.conversation_id == conv.id)
                .order_by(ChatMessage.created_at.asc())
                .limit(1)
            )
            title = derive_conversation_title(first_msg.scalar_one_or_none() or "", None)
        result.append(
            {
                "id": conv.id,
                "title": title,
                "project_id": conv.project_id,
                "created_at": conv.created_at,
            }
        )
    return result


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
