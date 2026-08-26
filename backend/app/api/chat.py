from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import re

from app.api.dependencies import get_current_user, DbSession
from app.models.user import User, UserRole
from app.models.chat import Conversation, ChatMessage
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert
from app.schemas.chat import ChatAttachment
from app.services.chat_payloads import (
    build_attachment_response_guidance,
    build_message_content,
    derive_conversation_title,
    looks_like_image_generation_request,
    storage_text,
)
from app.services.generated_files import GeneratedFile, build_generated_file_bytes_with_fallback, extract_generated_files
from app.services.project_storage import build_project_files_context
import base64

router = APIRouter(prefix="/chat", tags=["chat"]) 

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None
    generated_files: list[dict[str, str]] = Field(default_factory=list)


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
        "Hippo AI wurde im August 2026 von Valère Youbi, CEO der MERVAL DIGITALE, entwickelt.\n"
        "Hippo AI gehört der Firma HIPPOSIDEROS.\n\n"
        "WICHTIG:\n"
        "- Antworte direkt auf die Frage des Benutzers.\n"
        "- Gib niemals deine internen Gedanken, Überlegungen oder Analysen aus.\n"
        "- Gib niemals Formulierungen wie \"Okay, the user said...\", \"I need to...\", \"Let me check...\" aus.\n"
        "- Gib ausschließlich die fertige Antwort an den Benutzer zurück.\n"
        "- Antworte in der Sprache des Benutzers.\n"
        "- Wenn der Benutzer Deutsch schreibt, antworte auf Deutsch.\n"
        "- Wenn der Benutzer Französisch schreibt, antworte auf Französisch.\n"
        "- Wenn der Benutzer Englisch schreibt, antworte auf Englisch.\n"
        "- Wenn Bilder, Screenshots oder Dokumente angehängt sind, nutze die lokal extrahierten Textdaten im Prompt und sage nicht, dass du Anhänge nicht lesen kannst.\n"
        "- Wenn eine Datei, ein Bild oder der gemeinsame Projektordner analysiert werden soll, antworte ausführlicher, mit klaren Abschnitten, Aufzählungen und einer kurzen Schlussbewertung.\n"
        "- Wenn der Benutzer ausdrücklich ein Bild, ein PNG oder eine Grafik generieren möchte, liefere einen echten Dateiblock mit einem Bilddateinamen und keine Anleitung zur manuellen Erstellung.\n"
        "- Nenne bei Ordneranalysen zuerst den Überblick, dann die sichtbaren Dateien, dann die Details pro Datei und am Ende ein kurzes Fazit.\n"
        "- Schreibe Berichte mit sauberen Überschriften, Absätzen und Listen. Vermeide dekorative Markdown-Formate wie ###** oder **###.\n"
        "- Nutze Tabellen nur, wenn sie wirklich klarer sind als Listen.\n"
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
            "If the user explicitly requests an image or PNG, return a real file block with an image filename instead of prose instructions.\n"
            "If the user asks to analyze documents from the shared folder, use the project context and answer in the user's language.\n"
            "For shared-folder questions, produce a detailed answer with overview, file list, per-file observations, and a short conclusion.\n"
            "Write the answer as a polished document with clear section headings, paragraphs, and bullets. Avoid decorative Markdown around headings.\n"
            "If an image, screenshot, or document is attached, analyze the locally extracted text and metadata; do not claim that you cannot read attachments.\n"
            f"{build_attachment_response_guidance()}"
        )
        hippo_messages.insert(1, {"role": "system", "content": project_sys})

        try:
            project_files_context = build_project_files_context(conv_project)
            hippo_messages.insert(
                2,
                {
                    "role": "system",
                    "content": (
                        "Kontext des gemeinsamen Projektordners:\n"
                        f"{project_files_context}\n\n"
                        "Wenn der Benutzer nach dem Inhalt des Ordners fragt, antworte ausführlich auf Deutsch, stütze dich direkt auf diesen Kontext und vermeide Tabellen oder übertriebenes Markdown."
                    ),
                },
            )
        except Exception:
            pass

    if payload.attachments:
        hippo_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=False)

    # Call Hippo model endpoint if configured (preferred)
    import httpx
    reply_text = ''
    if settings.hippo_api_url and settings.hippo_api_key:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {"Authorization": f"Bearer {settings.hippo_api_key}", "Content-Type": "application/json"}
            model_name = settings.hippo_model
            model_payload = {
                "model": model_name,
                "messages": hippo_messages,
                "temperature": 0.45 if (payload.attachments or conv_project is not None) else 0.7,
                "max_tokens": 1600 if (payload.attachments or conv_project is not None) else 700,
            }
            try:
                r = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=model_payload, headers=headers)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and data.get('choices'):
                    reply_text = data['choices'][0]['message']['content']
                else:
                    reply_text = str(data)
            except httpx.HTTPStatusError:
                raise
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Hippo API error: {e}")
    else:
        raise HTTPException(status_code=503, detail="Die Hippo-API ist nicht konfiguriert. Bitte HIPPO_API_URL und HIPPO_API_KEY setzen.")

    # sanitize assistant reply: remove any <think>...</think> reasoning tags
    try:
        reply_text = re.sub(r"<think>[\s\S]*?<\/think>", "", reply_text, flags=re.IGNORECASE)
    except Exception:
        pass

    generated_files, cleaned_reply = extract_generated_files(reply_text)
    used_image_fallback = False
    if not generated_files and looks_like_image_generation_request(payload.message, payload.attachments):
        fallback_title = derive_conversation_title(payload.message, payload.attachments)
        fallback_name = re.sub(r"[^A-Za-z0-9]+", "_", fallback_title).strip("_").lower() or "hippo_image"
        generated_files = [
            GeneratedFile(
                filename=f"{fallback_name}.png",
                content=cleaned_reply or reply_text or payload.message,
            )
        ]
        used_image_fallback = True
    serialized_files: list[dict[str, str]] = []
    for file in generated_files:
        try:
            data, mime_type, filename = build_generated_file_bytes_with_fallback(file.filename, file.content)
        except Exception:
            # Never fail the whole chat because a generated artifact could not be rendered.
            continue
        serialized_files.append(
            {
                "filename": filename,
                "mime_type": mime_type,
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
        )
    if used_image_fallback:
        reply_text = "Datei wurde erstellt."
    elif cleaned_reply:
        reply_text = cleaned_reply
    elif generated_files:
        reply_text = "Datei wurde erstellt."

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

    return ChatResponse(reply=reply_text, conversation_id=conv_id, generated_files=serialized_files)


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
