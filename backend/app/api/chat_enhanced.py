from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.api.dependencies import get_current_user, DbSession
from app.models.user import User
from app.models.chat import Conversation, ChatMessage
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert
import httpx
from app.schemas.chat import ChatAttachment
from app.services.chat_payloads import build_message_content, derive_conversation_title, storage_text
from app.services.generated_files import extract_generated_files, save_generated_file

router = APIRouter(prefix="/chat-enhanced", tags=["chat-enhanced"]) 

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None


@router.post('/', response_model=ChatResponse)
async def chat_enhanced(payload: ChatRequest, db: DbSession, current_user: User = Depends(get_current_user)) -> ChatResponse:
    # basic project permission checks
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

    if payload.attachments:
        hippo_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=True)

    # global system prompt
    global_sys = (
        "Du bist Hippo, ein freundlicher und professioneller KI-Assistent.\n"
        "Hippo AI wurde im August 2026 von Valère Youbi, CEO der MERVAL DIGITALE, für HIPPOSIDEROS entwickelt.\n"
        "Hippo AI gehört zu HIPPOSIDEROS.\n"
        "Antworte in der Sprache des Benutzers.\n"
        "Nutze projektspezifisches Wissen, falls vorhanden, und verbinde es mit deinem Modellwissen zu einer einzigen, klaren Antwort."
    )
    hippo_messages.insert(0, {"role": "system", "content": global_sys})

    # if project provided, call embedding search service and inject context
    if payload.project_id is not None and settings.hippo_embedding_url:
        try:
            async with httpx.AsyncClient(timeout=30.0) as emb_client:
                emb_body = {"project_id": payload.project_id, "query": payload.message, "limit": 5, "min_score": 0.0}
                emb_resp = await emb_client.post(settings.hippo_embedding_url.rstrip('/') + '/embeddings/search', json=emb_body)
                emb_resp.raise_for_status()
                emb_data = emb_resp.json()
                results = emb_data.get('results') or emb_data.get('items') or emb_data.get('data') or emb_data.get('hits') or emb_data
                top_texts = []
                if isinstance(results, list):
                    for it in results[:5]:
                        t = it.get('text') if isinstance(it, dict) else (it if isinstance(it, str) else None)
                        if t:
                            top_texts.append(t)
                if top_texts:
                    context_block = '\n\n'.join(f"- {text}" for text in top_texts)
                    emb_sys = (
                        "Gefundene Projekthinweise aus dem Embedding-Store:\n"
                        f"{context_block}\n\n"
                        "Verwende diese Hinweise als Faktenbasis und mische sie mit deinen eigenen Schlussfolgerungen."
                    )
                    hippo_messages.insert(1, {"role": "system", "content": emb_sys})
        except Exception:
            pass

    fallback_messages = [dict(item) for item in hippo_messages]
    if payload.attachments:
        fallback_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=False)

    # call Hippo chat completions
    if not (settings.hippo_api_url and settings.hippo_api_key):
        raise HTTPException(status_code=503, detail='Die Hippo-API ist nicht konfiguriert.')

    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"Authorization": f"Bearer {settings.hippo_api_key}", "Content-Type": "application/json"}
        payload_h = {"model": settings.hippo_model, "messages": hippo_messages, "temperature": 0.7, "max_tokens": 512}
        try:
            r = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=payload_h, headers=headers)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get('choices'):
                reply_text = data['choices'][0]['message']['content']
            else:
                reply_text = str(data)
        except httpx.HTTPStatusError as e:
            if payload.attachments and e.response is not None and e.response.status_code == 400:
                retry_payload = {"model": settings.hippo_model, "messages": fallback_messages, "temperature": 0.7, "max_tokens": 512}
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
            raise HTTPException(status_code=502, detail=f'Fehler der Hippo-API: {e}')

    # sanitize & store
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

    await db.execute(insert(ChatMessage).values(conversation_id=conv_id, user_id=current_user.id, role='assistant', content=reply_text))
    await db.commit()

    return ChatResponse(reply=reply_text, conversation_id=conv_id)
