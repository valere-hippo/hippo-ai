from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import re
from pathlib import Path
import logging

from app.api.dependencies import get_current_user, DbSession
from app.models.user import User, UserRole
from app.models.chat import Conversation, ChatMessage
from app.models.conversation_memory import ConversationMemory
from app.services.conversation_threads import choose_project_conversation_id
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert, update
from app.schemas.chat import ChatAttachment
from app.services.chat_payloads import (
    build_attachment_response_guidance,
    build_message_content,
    derive_conversation_title,
    storage_text,
    looks_like_file_generation_request,
    looks_like_project_detailed_report_request,
)
from app.services.generated_files import build_generated_file_bytes_with_fallback, extract_generated_files
from app.services.chat_profiles import load_chat_profile, build_chat_profile_context, build_profile_system_prompt
from app.services.conversation_memory import build_conversation_memory_context, load_conversation_memory, refresh_conversation_memory, save_conversation_memory
from app.services.project_storage import build_project_files_context
from app.services.project_report_fallback import build_project_report_generated_file, build_project_report_fallback, _is_valid_report_text
from app.services.workflow_orchestration import ensure_workflow_for_message
from app.services.workflow_executor import execute_workflow
from app.services.workflow_planner import summarize_workflow_execution, build_workflow_summary_generated_file, build_workflow_task_generated_files
from app.services.project_skills import build_project_skills_context
from app.services.project_tools import build_tools_context
from app.services.model_registry import resolve_chat_max_tokens
from app.services.hippo_identity import build_hippo_system_prompt
import base64
import json

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger("hippo-ai.chat")


def _normalize_chat_base_url(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    if raw.endswith("/v1/chat/completions"):
        return raw
    if raw.endswith("/v1"):
        return f"{raw}/chat/completions"
    return f"{raw}/v1/chat/completions"


def _uses_openai_reasoning_completions(model_name: str | None) -> bool:
    raw = (model_name or "").strip().lower()
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw.startswith("gpt-5") or raw.startswith("o1") or raw.startswith("o3") or raw.startswith("o4")

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    profile_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None
    project_folder_context: str | None = None
    project_source_prefixes: list[str] | None = None

class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None
    generated_files: list[dict[str, str]] = Field(default_factory=list)
    file_output_requested: bool = False
    workflow_id: int | None = None
    workflow_plan: dict | None = None
    workflow_summary: dict | None = None
    workflow_resolution: dict | None = None


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


class ConversationMemoryResponse(BaseModel):
    conversation_id: int
    summary_text: str | None = None
    facts_text: str | None = None
    updated_at: str | None = None


class ConversationMemoryUpdateRequest(BaseModel):
    summary_text: str | None = Field(default=None, max_length=20000)
    facts_text: str | None = Field(default=None, max_length=20000)


def _serialize_message(message: ChatMessage) -> dict[str, object]:
    return {
        'id': message.id,
        'conversation_id': message.conversation_id,
        'user_id': message.user_id,
        'role': message.role,
        'content': message.content,
        'created_at': message.created_at.isoformat() if message.created_at else None,
    }


async def chat(payload: ChatRequest, db: DbSession, current_user: User = Depends(get_current_user)) -> ChatResponse:
    current_user_id = int(current_user.id)
    rag_sources: list[dict[str, object]] = []
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

    resolved_profile_id = payload.profile_id
    if resolved_profile_id is None and payload.conversation_id is not None:
        profile_result = await db.execute(select(Conversation.profile_id).where(Conversation.id == payload.conversation_id))
        resolved_profile_id = profile_result.scalar_one_or_none()
    if resolved_profile_id is None and conv_project is not None:
        project_profile_result = await db.execute(select(Project.default_profile_id).where(Project.id == conv_project.id))
        resolved_profile_id = project_profile_result.scalar_one_or_none()

    profile = None
    if resolved_profile_id is not None:
        profile = await load_chat_profile(db, int(resolved_profile_id))
        if profile is not None and profile.project_id is not None and profile.project_id != (conv_project.id if conv_project else profile.project_id):
            raise HTTPException(status_code=403, detail='Profil gehört zu einem anderen Projekt.')
        if profile is not None and profile.owner_id not in {current_user_id, getattr(conv_project, 'owner_id', current_user_id)} and current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail='Zugriff verweigert.')

    # ensure conversation
    conv_id = payload.conversation_id
    if conv_project is not None:
        existing_conversations = await db.execute(
            select(Conversation)
            .where(Conversation.project_id == conv_project.id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        )
        conv_id = choose_project_conversation_id(
            existing_conversations.scalars().all(),
            conv_project.id,
            getattr(conv_project, 'active_conversation_id', None),
            resolved_profile_id,
        )
    if conv_id is None:
        stmt = insert(Conversation).values(
            title=None,
            project_id=conv_project.id if conv_project else None,
            profile_id=resolved_profile_id,
        ).returning(Conversation)
        result = await db.execute(stmt)
        conv = result.scalar_one()
        conv_id = conv.id
        if conv_project is not None:
            await db.execute(
                Project.__table__.update().where(Project.id == conv_project.id).values(active_conversation_id=conv_id)
            )
            await db.commit()
    elif conv_project is not None and int(getattr(conv_project, 'active_conversation_id', 0) or 0) != int(conv_id):
        await db.execute(
            Project.__table__.update().where(Project.id == conv_project.id).values(active_conversation_id=conv_id)
        )
        await db.commit()

    if resolved_profile_id is not None:
        await db.execute(Conversation.__table__.update().where(Conversation.id == conv_id).values(profile_id=resolved_profile_id))
        await db.commit()

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

    memory = await load_conversation_memory(db, conv_id)
    hippo_messages = [{"role": "system", "content": build_hippo_system_prompt()}]
    if profile is not None:
        profile_context = build_chat_profile_context(profile, conv_project.name if conv_project else None)
        if profile_context:
            hippo_messages.append({"role": "system", "content": profile_context})
    if memory is not None:
        memory_context = build_conversation_memory_context(memory)
        if memory_context:
            hippo_messages.append({"role": "system", "content": memory_context})

    # If conversation is tied to a project, inform the assistant it may generate files for that project
    if conv_project is not None:
        project_sys = (
            "You are assisting a user within a project. The project may have local project folders where generated files are saved.\n"
            "If the user asks for a deliverable file (Word, PDF, image, SVG, report, exported document), return exactly one file block and no extra commentary.\n"
            "If the user only asks a question, wants an explanation, or wants a simple answer, respond as plain chat text and do not create a file.\n"
            "Use this format for files:\n"
            "<<<FILE:filename.ext>>>\n"
            "<file content here>\n"
            "<<<END_FILE>>>\n"
            "For .docx and .pdf, provide the final document text/content. For .svg, provide valid SVG markup. For raster images (.png/.jpg/.jpeg), return one exact image file block with the final visual scene or prompt content and do not add explanatory prose after it.\n"
            "If the user explicitly requests an image or PNG, return a real file block with an image filename instead of prose instructions. If the user only wants analysis or a textual answer, respond in text and do not create an image file.\n"
            "If the user asks to analyze documents from the project folders, use the project context and answer in the user's language.\n"
            "If the user wants project files analyzed or wants QGIS to work with the project folder, and project_folder_context is present, use that context directly and do not ask for a specific file; only ask for /datei when no project context is available.\n"
            "If the user asks for a report or analysis, do not answer with a preliminary acknowledgement like 'I will analyze' or 'I am analyzing'; provide the substantive analysis directly in the first reply.\n"
            "If the user mentions an explicit file path or filename, read that exact file directly from the project context and do not ask for a scan.\n"
            "If the user gives a Windows path for a file or folder, treat it as direct filesystem input and read it directly; do not route it through a scan-first fallback.\n"
            "If project_folder_context is present, treat it as the source of truth for the project folder contents and do not claim you lack local filesystem access. When it is structured as file-by-file blocks, read each file block completely, not just the filenames. If the user explicitly requested QGIS, do not ask which single file to open when the project context already lists relevant project files; use the listed files directly. If the project spans multiple folders or subfolders, analyze all of them together unless the user explicitly narrows the scope.\n"
            "If the project has a saved local folder, do not say you cannot access it; use the project context or ask for a refresh instead.\n"
            "For project-folder questions, prefer a short direct folder listing over any deep scan, and do not block the chat while waiting for recursive indexing.\n"
            "Open or launch QGIS only when the user explicitly asks for QGIS or explicitly asks to load the files in QGIS. If the user only wants an analysis or a report, read the file contents directly and answer without starting QGIS. When QGIS is requested together with project files, do not ask for a single file; use the available project files from context.\n"
            "When the user asks for a report, analysis, or Word/PDF deliverable from the project folders, answer in chat first. Only create a file when the user explicitly asks to save/export it as a document.\n"
            "Write in a polished Claude-like report style: direct, structured, concise but thorough, no preamble, no self-referential commentary, no repetitive reassurance, and minimize transitional phrases.\n"
            "For project-folder questions, produce a detailed answer that is content-first: describe what the files contain, what the extracted text / geometry / OCR / transcript says, and what technical conclusions follow. Prefer paragraphs over bullet lists unless bullets add real clarity. Do not lead with file size or filename inventory unless it is genuinely relevant.\n"
            "When the user asks for a report, aim for a Gutachten-like depth: use a real title page style, an index-like structure, separated subsections, and if several species, files, or themes appear, treat them separately instead of merging them into one short generic block.\n"
            "For report or analysis requests, prefer substantial detail over brevity: explain what was found, why it matters, what it implies technically and fachlich, and what consequences follow for the project.\n"
            "Write the answer as a polished document with clear section headings and concise paragraphs. Prefer a three-part structure when possible: summary, analysis, conclusion. Avoid decorative Markdown around headings.\n"
            "If an image, screenshot, or document is attached, rely on the direct attachment data in the prompt and any locally extracted text; do not claim that you cannot read attachments.\n"
            "For SHP/SHX/DBF/PRJ/CPG data, interpret the geodata as ecological field data when appropriate and surface contact counts, seasonality, habitat clues, and spatial clusters.\n"
            f"{build_attachment_response_guidance()}"
        )
        hippo_messages.append({"role": "system", "content": project_sys})

        project_memory_context = []
        if getattr(conv_project, 'memory_summary', None):
            project_memory_context.append('Projekt-Memory-Zusammenfassung:')
            project_memory_context.append(str(conv_project.memory_summary).strip())
        if getattr(conv_project, 'memory_facts', None):
            project_memory_context.append('Projekt-Memory-Fakten:')
            project_memory_context.append(str(conv_project.memory_facts).strip())
        if project_memory_context:
            hippo_messages.append({
                "role": "system",
                "content": "\n".join(project_memory_context),
            })

        tool_skill_context_parts: list[str] = []
        try:
            tools_context = await build_tools_context(db, query=payload.message, limit=6, user_id=current_user_id, project_id=conv_project.id)
            if tools_context.strip():
                tool_skill_context_parts.append("Aktive Projekt-Tools:\n" + tools_context.strip())
            skills_context = await build_project_skills_context(db, conv_project.id, user_id=current_user_id, query=payload.message, limit=6)
            if skills_context.strip():
                tool_skill_context_parts.append("Aktive Projekt-Skills:\n" + skills_context.strip())
            if tool_skill_context_parts:
                hippo_messages.append({
                    "role": "system",
                    "content": (
                        "Aktivierte Werkzeuge und Skills für diese Unterhaltung:\n"
                        + "\n\n".join(tool_skill_context_parts)
                        + "\n\nNutze diese Tools und Skills als Arbeitsanweisung, nicht als Ersatz für die echten Datei- und Ordnerinhalte."
                    ),
                })
        except Exception:
            pass

        project_context_parts: list[str] = []
        project_files_context = ''
        try:
            direct_context = (payload.project_folder_context or '').strip()
            if conv_project is not None and not payload.attachments:
                backend_project_context = await build_project_files_context(
                    conv_project,
                    include_previews=True,
                    question=payload.message,
                    source_prefixes=payload.project_source_prefixes,
                )
                if backend_project_context.strip():
                    project_context_parts.append(backend_project_context.strip())
            if direct_context and not project_context_parts:
                project_context_parts.append(direct_context)
            if not project_context_parts:
                project_context_parts.append(
                    "Der Desktop-Agent ist aktiv und kann den Computer bedienen. "
                    "Lokale Projektordner werden direkt über den vorhandenen Projektkontext gelesen; "
                    "wenn der Kontext noch leer ist, antworte ohne erfundene Dateinamen und bitte nur um eine kurze direkte Ordnerauflistung."
                )
            project_files_context = "\n\n".join(project_context_parts)
            hippo_messages.append(
                {
                    "role": "system",
                    "content": (
                        "Kontext der lokalen Projektordner:\n"
                        f"{project_files_context}\n\n"
                        "Nutze diesen Kontext, wenn der Benutzer die Dateien oder den Ordner analysieren möchte, antworte ausführlich auf Deutsch und vermeide Tabellen oder übertriebenes Markdown.\n"
                        "Wenn der Request bereits echte Dateianhänge enthält, behandle diese Anhänge als primäre Quelle und lies ihren Inhalt direkt statt bloß Ordnerlisten oder QGIS-Hinweise zu verwenden.\n"
                        "Wenn der Benutzer einen Bericht, ein Word-Dokument oder einen PDF-Export aus dem Projektordner möchte, verwende automatisch alle verfügbaren Ordner und Dateien des Projekts, ohne nach bestimmten Dateien oder Unterordnern zu fragen, sofern der Benutzer die Auswahl nicht explizit einschränkt."
                    ),
                },
            )
        except Exception:
            pass

    recent_messages = messages[-18:]
    workflow_plan: dict[str, object] | None = None
    try:
        workflow_plan = await ensure_workflow_for_message(
            db,
            current_user=current_user,
            conversation_id=conv_id,
            project_id=conv_project.id if conv_project else None,
            source_message=payload.message,
            final_model_tag=profile.model_name if profile and profile.model_name else None,
        )
        if workflow_plan:
            hippo_messages.append(
                {
                    "role": "system",
                    "content": (
                        "Erkannter Multi-Modell-Workflow:\n"
                        f"{json.dumps(workflow_plan, ensure_ascii=False, indent=2)}\n\n"
                        "Nutze den Workflow als Leitstruktur für die Antwort. Wenn mehrere Modelle markiert sind, gib eine präzise zusammengefasste Antwort und halte die Reihenfolge und Abhängigkeiten logisch ein."
                    ),
                }
            )
    except Exception:
        workflow_plan = None
    for m in recent_messages:
        role = 'user' if m.role == 'user' else 'assistant' if m.role == 'assistant' else 'system'
        hippo_messages.append({"role": role, "content": m.content})

    if payload.attachments:
        hippo_messages[-1]["content"] = build_message_content(payload.message, payload.attachments, include_images=True)

    reply_text = ''
    workflow_execution_result = None
    if workflow_plan:
        workflow_id = int(str(workflow_plan.get('workflow_id') or '0'))
        if workflow_id <= 0:
            raise HTTPException(status_code=500, detail="Workflow-ID missing from workflow plan")
        workflow_execution_result = await execute_workflow(db, workflow_id)
        reply_text = summarize_workflow_execution(workflow_plan, workflow_execution_result)
    else:
        # Call Hippo model endpoint if configured (preferred)
        import httpx
        if not settings.hippo_api_url:
            raise HTTPException(status_code=503, detail="Die Hippo-API ist nicht konfiguriert. Bitte HIPPO_AI_BASE_URL und HIPPO_AI_MODEL setzen.")

        request_timeout = int(getattr(settings, 'hippo_response_timeout_seconds_long' if (payload.attachments or conv_project is not None) else 'hippo_response_timeout_seconds', 600) or 600)
        request_timeout = max(120, request_timeout)
        async with httpx.AsyncClient(timeout=httpx.Timeout(request_timeout, connect=15.0)) as client:
            headers = {"Content-Type": "application/json"}
            if settings.hippo_api_key:
                headers["Authorization"] = f"Bearer {settings.hippo_api_key}"
            model_name = settings.hippo_model
            chat_api_url = _normalize_chat_base_url(settings.hippo_api_url)
            if not chat_api_url:
                raise HTTPException(status_code=503, detail="Die Hippo-API ist nicht konfiguriert. Bitte HIPPO_AI_BASE_URL und HIPPO_AI_MODEL setzen.")
            max_tokens = await resolve_chat_max_tokens(db, settings.hippo_response_max_tokens, settings.hippo_response_max_tokens_long)
            if payload.attachments or conv_project is not None:
                max_tokens = max(512, min(max_tokens, settings.hippo_response_max_tokens_long))
            reasoning_model = _uses_openai_reasoning_completions(model_name)
            model_payload = {
                "model": model_name,
                "messages": hippo_messages,
                "max_completion_tokens": max_tokens if reasoning_model else None,
                "temperature": None if reasoning_model else (0.45 if (payload.attachments or conv_project is not None) else 0.7),
            }
            if not reasoning_model:
                model_payload["max_tokens"] = max_tokens
                model_payload.pop("max_completion_tokens", None)
                model_payload.pop("temperature", None)
            else:
                model_payload.pop("temperature", None)
            logger.info(
                "Calling Hippo model | url=%s | model=%s | max_tokens=%s | timeout=%s | auth=%s | project=%s | attachments=%s",
                settings.hippo_api_url,
                model_name,
                max_tokens,
                request_timeout,
                bool(settings.hippo_api_key),
                getattr(conv_project, 'id', None),
                bool(payload.attachments),
            )
            try:
                r = await client.post(chat_api_url, json=model_payload, headers=headers)
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

    generated_files, cleaned_reply = extract_generated_files(reply_text)
    if cleaned_reply:
        reply_text = cleaned_reply
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

    explicit_file_request = False
    if conv_project is not None and not serialized_files:
        try:
            explicit_file_request = looks_like_file_generation_request(payload.message, payload.attachments) or looks_like_project_detailed_report_request(payload.message)
            if explicit_file_request:
                report_text = (reply_text or '').strip()
                if not _is_valid_report_text(report_text):
                    report_text = build_project_report_fallback(
                        payload.message,
                        project_files_context or reply_text,
                        project_name=conv_project.name if conv_project else None,
                    )
                data, mime_type, filename = build_project_report_generated_file(
                    payload.message,
                    report_text,
                    project_name=conv_project.name if conv_project else None,
                    filename_hint='project_report',
                )
                serialized_files.append(
                    {
                        'filename': filename,
                        'data_base64': base64.b64encode(data).decode('ascii'),
                        'mime_type': mime_type,
                    }
                )
                reply_text = report_text
        except Exception:
            logger.warning('Auto report generation failed for conversation %s', conv_id)

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

    try:
        await refresh_conversation_memory(
            db,
            conv_id,
            recent_messages=messages[-18:],
            assistant_reply=reply_text,
            project_name=conv_project.name if conv_project else None,
            profile_name=getattr(profile, 'name', None),
        )
    except Exception:
        logger.warning("conversation memory update failed for conversation %s", conv_id)

    workflow_id = None
    workflow_summary = None
    workflow_resolution = None
    if workflow_plan:
        workflow_id_value = workflow_plan.get('workflow_id')
        if isinstance(workflow_id_value, int):
            workflow_id = workflow_id_value
        elif workflow_id_value is not None:
            try:
                workflow_id = int(str(workflow_id_value))
            except Exception:
                workflow_id = None
        workflow_summary = workflow_execution_result.get('summary') if isinstance(workflow_execution_result, dict) else None
        workflow_resolution = workflow_execution_result.get('resolution') if isinstance(workflow_execution_result, dict) else None
        if workflow_resolution:
            choices = workflow_resolution.get('choices') or []
            choice_labels = ', '.join(choice.get('label') for choice in choices if choice.get('label'))
            reply_text = (
                f"Le modèle demandé n’est pas disponible pour cette tâche. "
                f"Erreur: {workflow_resolution.get('error_message') or 'modèle indisponible'}. "
                + (f"Choisis un autre modèle: {choice_labels}." if choice_labels else "Choisis un autre modèle.")
            )
    if workflow_plan and workflow_execution_result and isinstance(workflow_execution_result, dict) and explicit_file_request:
        try:
            workflow_summary = workflow_execution_result.get('summary') if isinstance(workflow_execution_result.get('summary'), dict) else None
            task_sources = workflow_summary or workflow_execution_result.get('summary') or workflow_plan
            for file_data, mime_type, filename in build_workflow_task_generated_files(task_sources if isinstance(task_sources, dict) else workflow_plan):
                serialized_files.append(
                    {
                        'filename': filename,
                        'mime_type': mime_type,
                        'data_base64': base64.b64encode(file_data).decode('ascii'),
                    }
                )
            file_data, mime_type, filename = build_workflow_summary_generated_file(workflow_plan, workflow_execution_result)
            serialized_files.append(
                {
                    'filename': filename,
                    'mime_type': mime_type,
                    'data_base64': base64.b64encode(file_data).decode('ascii'),
                }
            )
        except Exception:
            logger.warning('workflow summary export failed for conversation %s', conv_id)

    return ChatResponse(
        reply=reply_text,
        conversation_id=conv_id,
        generated_files=serialized_files,
        file_output_requested=explicit_file_request,
        workflow_id=workflow_id,
        workflow_plan=workflow_plan,
        workflow_summary=workflow_summary,
        workflow_resolution=workflow_resolution,
    )


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
                "profile_id": getattr(conv, 'profile_id', None),
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
    memory = await load_conversation_memory(db, conv_id)
    return {
        'conversation': {
            'id': conv.id,
            'title': conv.title,
            'project_id': conv.project_id,
            'profile_id': getattr(conv, 'profile_id', None),
            'created_at': conv.created_at.isoformat() if conv.created_at else None,
        },
        'messages': messages,
        'memory': {
            'conversation_id': conv_id,
            'summary_text': getattr(memory, 'summary_text', None),
            'facts_text': getattr(memory, 'facts_text', None),
            'updated_at': memory.updated_at.isoformat() if memory is not None and memory.updated_at else None,
        },
    }


@router.put('/conversations/{conv_id}/memory')
async def update_conversation_memory(conv_id: int, payload: ConversationMemoryUpdateRequest, db: DbSession, current_user: User = Depends(get_current_user)):
    res = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = res.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail='Nicht gefunden.')
    if conv.project_id is not None:
        result = await db.execute(select(Project).where(Project.id == conv.project_id))
        proj = result.scalar_one_or_none()
        from app.services.permissions import has_project_permission
        allowed = await has_project_permission(db, current_user, proj, PermissionLevel.READ)
        if not allowed:
            raise HTTPException(status_code=403, detail='Zugriff verweigert.')

    summary_text = (payload.summary_text or '').strip()
    facts_text = (payload.facts_text or '').strip()
    await save_conversation_memory(db, conv_id, summary_text, facts_text)
    memory = await load_conversation_memory(db, conv_id)
    return {
        'conversation_id': conv_id,
        'summary_text': getattr(memory, 'summary_text', None),
        'facts_text': getattr(memory, 'facts_text', None),
        'updated_at': memory.updated_at.isoformat() if memory is not None and memory.updated_at else None,
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
    await db.execute(
        Project.__table__.update()
        .where(Project.active_conversation_id == conv_id)
        .values(active_conversation_id=None)
    )
    await db.commit()
    return {'ok': True}
