from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.api.dependencies import get_current_user, DbSession
from app.models.user import User
from app.models.chat import Conversation, ChatMessage
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert
import httpx
from app.schemas.chat import ChatAttachment
from app.services.chat_payloads import build_attachment_response_guidance, build_message_content, derive_conversation_title, storage_text
from app.services.generated_files import build_generated_file_bytes, extract_generated_files
from app.services.project_storage import build_project_files_context
import base64

router = APIRouter(prefix="/chat-enhanced", tags=["chat-enhanced"]) 

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None
    generated_files: list[dict[str, str]] = Field(default_factory=list)


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
        hippo_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=False)

    # global system prompt
    global_sys = (
        "Du bist Hippo, ein freundlicher und professioneller KI-Assistent.\n"
        "Hippo AI wurde im August 2026 von Valère Youbi, CEO der MERVAL DIGITALE, entwickelt.\n"
        "Hippo AI gehört der Firma HIPPOSIDEROS.\n"
        "Antworte in der Sprache des Benutzers.\n"
        "Nutze projektspezifisches Wissen, falls vorhanden, und verbinde es mit deinem Modellwissen zu einer einzigen, klaren Antwort.\n"
        "Wenn Bilder, Screenshots oder Dokumente angehängt sind, nutze die lokal extrahierten Textdaten im Prompt und sage nicht, dass du Anhänge nicht lesen kannst.\n"
        "Wenn eine Datei oder ein Bild analysiert wird, antworte ausführlich, strukturiert und mit klaren Zwischenüberschriften oder Aufzählungspunkten."
    )
    hippo_messages.insert(0, {"role": "system", "content": global_sys})

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
            "If the user asks to analyze documents from the shared folder, use the project context and answer in the user's language.\n"
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
                        "Contexte des fichiers du dossier partagé du projet:\n"
                        f"{project_files_context}\n\n"
                        "Utilise ce contexte pour répondre quand l'utilisateur demande d'analyser les fichiers du dossier."
                    ),
                },
            )
        except Exception:
            pass

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

    # call Hippo chat completions
    if not (settings.hippo_api_url and settings.hippo_api_key):
        raise HTTPException(status_code=503, detail='Die Hippo-API ist nicht konfiguriert.')

    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"Authorization": f"Bearer {settings.hippo_api_key}", "Content-Type": "application/json"}
        model_name = settings.hippo_model
        payload_h = {
            "model": model_name,
            "messages": hippo_messages,
            "temperature": 0.65 if payload.attachments else 0.7,
            "max_tokens": 1100 if payload.attachments else 512,
        }
        try:
            r = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=payload_h, headers=headers)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get('choices'):
                reply_text = data['choices'][0]['message']['content']
            else:
                reply_text = str(data)
        except httpx.HTTPStatusError:
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
    serialized_files: list[dict[str, str]] = []
    for file in generated_files:
        data, mime_type = build_generated_file_bytes(file.filename, file.content)
        serialized_files.append(
            {
                "filename": file.filename,
                "mime_type": mime_type,
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
        )
    if cleaned_reply:
        reply_text = cleaned_reply
    elif generated_files:
        reply_text = "Datei wurde erstellt."

    await db.execute(insert(ChatMessage).values(conversation_id=conv_id, user_id=current_user.id, role='assistant', content=reply_text))
    await db.commit()

    return ChatResponse(reply=reply_text, conversation_id=conv_id, generated_files=serialized_files)
