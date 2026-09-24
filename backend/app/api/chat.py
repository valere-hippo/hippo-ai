from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import re
from pathlib import Path
import logging

from app.api.dependencies import get_current_user, DbSession
from app.models.user import User, UserRole
from app.models.chat import Conversation, ChatMessage
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert, update
from app.schemas.chat import ChatAttachment
from app.services.chat_payloads import (
    build_attachment_response_guidance,
    build_message_content,
    derive_conversation_title,
    looks_like_image_analysis_request,
    looks_like_geodata_visual_request,
    looks_like_image_generation_request,
    looks_like_file_generation_request,
    looks_like_project_inventory_request,
    storage_text,
)
from app.services.generated_files import GeneratedFile, SCENE_PREFIX, build_generated_file_bytes_with_fallback, extract_generated_files
from app.services.project_tools import build_tools_context
from app.services.vision_analysis import build_vision_enriched_text
from app.services.project_skills import build_project_skills_context, build_shared_skills_context
from app.services.project_storage import build_geodata_map_file, build_project_files_context
from app.services.model_registry import resolve_chat_max_tokens
from app.services.image_generation import build_image_scene_spec
from app.services.hippo_identity import build_hippo_system_prompt
import base64
import json

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger("hippo-ai.chat")

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None
    project_folder_context: str | None = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None
    generated_files: list[dict[str, str]] = Field(default_factory=list)


class ChatMessageResponse(BaseModel):
    id: int
    conversation_id: int
    user_id: int
    role: str
    content: str
    created_at: str


class ConversationResponse(BaseModel):
    id: int
    title: str | None
    created_at: str
    messages: list[ChatMessageResponse] | None = None


class ChatMessageEditRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)


def _serialize_message(message: ChatMessage) -> dict[str, object]:
    return {
        'id': message.id,
        'conversation_id': message.conversation_id,
        'user_id': message.user_id,
        'role': message.role,
        'content': message.content,
        'created_at': message.created_at.isoformat() if message.created_at else None,
    }


def _infer_generated_filename(message: str) -> str:
    text = (message or '').lower()
    if 'pdf' in text:
        return 'hippo-bericht.pdf'
    if any(token in text for token in ['svg', 'karte', 'map', 'diagramm', 'chart', 'grafik']):
        return 'hippo-bericht.svg'
    if any(token in text for token in ['png', 'jpg', 'jpeg', 'bild', 'image', 'foto', 'foto']):
        return 'hippo-bericht.png'
    if any(token in text for token in ['rtf']):
        return 'hippo-bericht.rtf'
    return 'hippo-bericht.docx'


async def chat(payload: ChatRequest, db: DbSession, current_user: User = Depends(get_current_user)) -> ChatResponse:
    current_user_id = int(current_user.id)
    resolved_project_id = payload.project_id
    if resolved_project_id is None and payload.conversation_id is not None:
        conv_result = await db.execute(select(Conversation.project_id).where(Conversation.id == payload.conversation_id))
        resolved_project_id = conv_result.scalar_one_or_none()
    # verify project permission if provided
    conv_project = None
    if resolved_project_id is not None:
        result = await db.execute(select(Project).where(Project.id == resolved_project_id))
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

    stored_message_content = storage_text(payload.message, payload.attachments)
    if not stored_message_content:
        stored_message_content = (payload.message or "").strip()

    # store user message
    await db.execute(
        insert(ChatMessage).values(
            conversation_id=conv_id,
            user_id=current_user_id,
            role='user',
            content=stored_message_content,
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

    hippo_messages.insert(0, {"role": "system", "content": build_hippo_system_prompt()})

    # If conversation is tied to a project, inform the assistant it may generate files for that project
    if conv_project is not None:
        project_sys = (
            "You are assisting a user within a project. The project may have a shared folder where generated files are saved.\n"
            "If the user asks for a deliverable file (Word, PDF, image, SVG, report, exported document), return exactly one file block and no extra commentary.\n"
            "If the user only asks a question, wants an explanation, or wants a simple answer, respond as plain chat text and do not create a file.\n"
            "Use this format for files:\n"
            "<<<FILE:filename.ext>>>\n"
            "<file content here>\n"
            "<<<END_FILE>>>\n"
            "For .docx and .pdf, provide the final document text/content. For .svg, provide valid SVG markup. For raster images (.png/.jpg/.jpeg), provide a concise visual description or poster brief that should be rendered into the image.\n"
            "If the user explicitly requests an image or PNG, return a real file block with an image filename instead of prose instructions. If the user only wants analysis or a textual answer, respond in text and do not create an image file.\n"
            "If the user asks to analyze documents from the shared folder, use the project context and answer in the user's language.\n"
            "If project_folder_context is present, treat it as the source of truth for the shared folder contents and do not claim you lack local filesystem access.\n"
            "For shared-folder questions, produce a detailed answer with overview, file list, per-file observations, and a short conclusion.\n"
            "Write the answer as a polished document with clear section headings, paragraphs, and bullets. Avoid decorative Markdown around headings.\n"
            "If an image, screenshot, or document is attached, rely on the direct attachment data in the prompt and any locally extracted text; do not claim that you cannot read attachments.\n"
            "For SHP/SHX/DBF/PRJ/CPG data, interpret the geodata as ecological field data when appropriate and surface contact counts, seasonality, habitat clues, and spatial clusters.\n"
            f"{build_attachment_response_guidance()}"
        )
        hippo_messages.insert(1, {"role": "system", "content": project_sys})

        try:
            if conv_project is not None:
                project_skills_context = await build_project_skills_context(db, conv_project.id, int(current_user.id), payload.message, limit=5)
            else:
                project_skills_context = await build_shared_skills_context(db, payload.message, limit=5)
            if project_skills_context:
                hippo_messages.insert(
                    2,
                    {
                        "role": "system",
                        "content": (
                            f"{project_skills_context}\n\n"
                            "Diese Skills gelten für jeden Chat dieses Projekts. Behandle sie als verbindliche Projektrichtlinien und priorisiere sie vor allgemeinen Formulierungen, solange sie der Benutzeranfrage nicht widersprechen."
                        ),
                    },
                )
        except Exception:
            pass

        try:
            project_files_context = await build_project_files_context(conv_project, include_previews=not looks_like_project_inventory_request(payload.message), question=payload.message)
            hippo_messages.insert(
                3,
                {
                    "role": "system",
                    "content": (
                        "Kontext des gemeinsamen Projektordners:\n"
                        f"{project_files_context}\n\n"
                        "Nutze diesen Kontext, wenn der Benutzer die Dateien oder den Ordner analysieren möchte, antworte ausführlich auf Deutsch und vermeide Tabellen oder übertriebenes Markdown."
                    ),
                },
            )
        except Exception:
            pass

        try:
            tools_context = await build_tools_context(db, payload.message, limit=6, user_id=int(current_user.id), project_id=conv_project.id if conv_project is not None else None)
            if tools_context:
                hippo_messages.insert(
                    4,
                    {
                        "role": "system",
                        "content": (
                            f"{tools_context}\n\n"
                            "Diese Tools stehen dem Agenten zur Verfügung. Nutze sie nur, wenn sie zur aktuellen Frage passen. "
                            "Bevorzuge klare, ausführbare Workflows statt allgemeiner Vermutungen."
                        ),
                    },
                )
        except Exception:
            pass

    if payload.attachments:
        hippo_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=True)

    # Call Hippo model endpoint if configured (preferred)
    import httpx
    reply_text = ''
    if not settings.hippo_api_url:
        raise HTTPException(status_code=503, detail="Die Hippo-API ist nicht konfiguriert. Bitte HIPPO_AI_BASE_URL und HIPPO_AI_MODEL setzen.")

    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"Content-Type": "application/json"}
        if settings.hippo_api_key:
            headers["Authorization"] = f"Bearer {settings.hippo_api_key}"
        model_name = settings.hippo_model
        max_tokens = await resolve_chat_max_tokens(db, settings.hippo_response_max_tokens, settings.hippo_response_max_tokens_long)
        if payload.attachments or conv_project is not None:
            max_tokens = max(512, min(max_tokens, settings.hippo_response_max_tokens_long))
        model_payload = {
            "model": model_name,
            "messages": hippo_messages,
            "temperature": 0.45 if (payload.attachments or conv_project is not None) else 0.7,
            "max_tokens": max_tokens,
            "max_completion_tokens": max_tokens,
            "max_output_tokens": max_tokens,
        }
        logger.info(
            "Calling Hippo model | url=%s | model=%s | max_tokens=%s | auth=%s | project=%s | attachments=%s",
            settings.hippo_api_url,
            model_name,
            max_tokens,
            bool(settings.hippo_api_key),
            getattr(conv_project, 'id', None),
            bool(payload.attachments),
        )
        try:
            r = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=model_payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get('choices'):
                reply_text = data['choices'][0]['message']['content']
            else:
                reply_text = str(data)
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = exc.response.text[:500]
            except Exception:
                pass
            raise HTTPException(
                status_code=502,
                detail=f"Hippo-API antwortete mit HTTP {exc.response.status_code}. {body}".strip(),
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Hippo API error: {e}")

    # sanitize assistant reply: remove any <think>...</think> reasoning tags
    try:
        reply_text = re.sub(r"<think>[\s\S]*?<\/think>", "", reply_text, flags=re.IGNORECASE)
    except Exception:
        pass

    generated_files, cleaned_reply = extract_generated_files(reply_text)
    file_request = looks_like_file_generation_request(payload.message, payload.attachments)
    image_request = looks_like_image_generation_request(payload.message, payload.attachments)
    geodata_visual_request = looks_like_geodata_visual_request(payload.message, payload.attachments)
    geodata_direct_svg: tuple[str, str] | None = None

    if image_request and conv_project is not None and geodata_visual_request:
        geodata_file = build_geodata_map_file(conv_project, payload.message)
        if geodata_file:
            generated_files = [GeneratedFile(filename=geodata_file[0], content=geodata_file[1])]
            geodata_direct_svg = geodata_file

    if file_request and not generated_files and (cleaned_reply or reply_text.strip()):
        generated_files = [GeneratedFile(filename=_infer_generated_filename(payload.message), content=(cleaned_reply or reply_text).strip())]

    has_image_attachment = any((getattr(att, 'mime_type', '') or '').lower().startswith('image/') for att in (payload.attachments or []))
    discarded_visual = False
    if has_image_attachment and not image_request and looks_like_image_analysis_request(payload.message, payload.attachments):
        if generated_files:
            discarded_visual = True
        generated_files = []

    if image_request and not geodata_visual_request:
        scene = await build_image_scene_spec(payload.message, cleaned_reply or reply_text)
        fallback_title = derive_conversation_title(payload.message, payload.attachments)
        fallback_name = re.sub(r"[^A-Za-z0-9]+", "_", fallback_title).strip("_").lower() or "hippo_image"
        generated_files = [
            GeneratedFile(
                filename=f"{fallback_name}.png",
                content=f"{SCENE_PREFIX}{json.dumps(scene, ensure_ascii=False)}",
            )
        ]
        used_image_fallback = True
    else:
        used_image_fallback = False
    serialized_files: list[dict[str, str]] = []
    for file in generated_files:
        try:
            if geodata_direct_svg and file.filename == geodata_direct_svg[0]:
                serialized_files.append(
                    {
                        "filename": file.filename,
                        "mime_type": "image/svg+xml",
                        "data_base64": base64.b64encode(file.content.encode("utf-8")).decode("ascii"),
                    }
                )
                continue
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
    elif geodata_direct_svg and not cleaned_reply:
        reply_text = "Karte wurde erstellt."
    elif discarded_visual and not cleaned_reply:
        reply_text = "Ich habe das Bild visuell analysiert, antworte aber bewusst als Text statt mit einer neuen Datei."
    elif cleaned_reply:
        reply_text = cleaned_reply
    elif generated_files:
        reply_text = "Datei wurde erstellt."

    # store assistant message
    await db.execute(
        insert(ChatMessage).values(
            conversation_id=conv_id,
            user_id=current_user_id,
            role='assistant',
            content=reply_text,
        )
    )
    await db.commit()

    return ChatResponse(reply=reply_text, conversation_id=conv_id, generated_files=serialized_files)


@router.get('/conversations')
async def list_conversations(db: DbSession, current_user: User = Depends(get_current_user)):
    current_user_id = int(current_user.id)
    # list conversations the user participated in or project-less owned
    q = (
        select(Conversation)
        .where(
            Conversation.id.in_(
                select(ChatMessage.conversation_id)
                .where(ChatMessage.user_id == current_user_id)
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
    messages = [_serialize_message(message) for message in msgs.scalars().all()]
    return {
        'conversation': {
            'id': conv.id,
            'title': conv.title,
            'project_id': conv.project_id,
            'created_at': conv.created_at.isoformat() if conv.created_at else None,
        },
        'messages': messages,
    }


@router.patch('/messages/{message_id}')
async def edit_message(message_id: int, payload: ChatMessageEditRequest, db: DbSession, current_user: User = Depends(get_current_user)):
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail='Nachricht nicht gefunden.')
    if current_user.role != UserRole.ADMIN and int(message.user_id) != int(current_user.id):
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    if message.role != 'user' and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=400, detail='Nur eigene Nachrichten können bearbeitet werden.')

    cleaned = (payload.content or '').strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail='Nachricht darf nicht leer sein.')

    await db.execute(
        update(ChatMessage).where(ChatMessage.id == message_id).values(content=cleaned)
    )
    await db.commit()

    first_msg = await db.execute(
        select(ChatMessage.id).where(ChatMessage.conversation_id == message.conversation_id).order_by(ChatMessage.created_at.asc()).limit(1)
    )
    if first_msg.scalar_one_or_none() == message_id:
        conv_title = derive_conversation_title(cleaned, None)
        await db.execute(
            update(Conversation).where(Conversation.id == message.conversation_id).values(title=conv_title)
        )
        await db.commit()

    refreshed = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    return _serialize_message(refreshed.scalar_one())


@router.delete('/conversations/{conv_id}')
async def delete_conversation(conv_id: int, db: DbSession, current_user: User = Depends(get_current_user)):
    current_user_id = int(current_user.id)
    # only allow deletion if user has participated or admin
    msgs = await db.execute(select(ChatMessage).where(ChatMessage.conversation_id == conv_id))
    msgs = msgs.scalars().all()
    if not msgs:
        raise HTTPException(status_code=404, detail='Nicht gefunden.')
    participant_ids = set(m.user_id for m in msgs)
    if current_user.role != UserRole.ADMIN and current_user_id not in participant_ids:
        raise HTTPException(status_code=403, detail='Zugriff verweigert.')
    await db.execute(ChatMessage.__table__.delete().where(ChatMessage.conversation_id == conv_id))
    await db.execute(Conversation.__table__.delete().where(Conversation.id == conv_id))
    await db.commit()
    return {'ok': True}
