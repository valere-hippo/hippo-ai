from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import re
from pathlib import Path
import logging
from app.api.dependencies import get_current_user, DbSession
from app.models.user import User, UserRole
from app.models.chat import Conversation, ChatMessage
from app.services.conversation_threads import choose_project_conversation_id
from app.models.project import Project
from app.models.permission import PermissionLevel
from app.core.config import settings
from sqlalchemy import select, insert
import httpx
from app.schemas.chat import ChatAttachment
from app.services.chat_payloads import (
    build_attachment_response_guidance,
    build_message_content,
    derive_conversation_title,
    storage_text,
)
from app.services.generated_files import build_generated_file_bytes_with_fallback, extract_generated_files
from app.services.chat_profiles import load_chat_profile, build_chat_profile_context, build_profile_system_prompt
from app.services.conversation_memory import build_conversation_memory_context, load_conversation_memory, refresh_conversation_memory
from app.services.project_storage import build_project_files_context
from app.services.project_skills import build_project_skills_context
from app.services.project_tools import build_tools_context
from app.services.desktop_workflows import infer_desktop_launch_actions
from app.services.model_registry import resolve_chat_max_tokens
from app.services.hippo_identity import build_hippo_system_prompt
import base64
import json

router = APIRouter(prefix="/chat-enhanced", tags=["chat"])
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

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    profile_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None
    desktop_agent: bool = False
    desktop_profile: str | None = None
    desktop_result: str | None = None
    project_folder_context: str | None = None
    project_source_prefixes: list[str] | None = None


class DesktopAction(BaseModel):
    action: str
    command: str | None = None
    args: str | None = None
    cwd: str | None = None
    file: str | None = None
    path: str | None = None
    keys: str | None = None
    text: str | None = None
    button: str | None = None
    x: float | None = None
    y: float | None = None
    direction: str | None = None
    amount: int | None = None
    wait_seconds: float | None = None


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int | None = None
    generated_files: list[dict[str, str]] = Field(default_factory=list)
    desktop_actions: list[DesktopAction] = Field(default_factory=list)


def _extract_json_object(text: str) -> dict | None:
    source = (text or '').strip()
    if not source:
        return None
    if source.startswith('{') and source.endswith('}'):
        try:
            parsed = json.loads(source)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass
    start = source.find('{')
    end = source.rfind('}')
    if start >= 0 and end > start:
        candidate = source[start:end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None




def _extract_candidate_open_path(text: str) -> str | None:
    source = text or ''
    executable_patterns = [
        r"[A-Za-z]:\\[^\"\n\r]+?\.(?:exe|app|bat|cmd|com)",
        r"/[^\"\n\r]+?\.(?:exe|app|bat|cmd|com)",
    ]
    for pattern in executable_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip().strip('"').strip("'")

    full_patterns = [
        r"[A-Za-z]:\\[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
        r"/[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
    ]
    for pattern in full_patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip().strip('"').strip("'")

    filename_pattern = r"[A-Za-z0-9À-ÿ._-]+\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)"
    filename_matches = list(re.finditer(filename_pattern, source, flags=re.IGNORECASE))
    if not filename_matches:
        return None
    file_match = filename_matches[-1]
    folder_starts = [m for m in re.finditer(r"[A-Za-z]:\\|/", source, flags=re.IGNORECASE) if m.start() < file_match.start()]
    if not folder_starts:
        return None
    folder_start = folder_starts[-1].start()
    prefix = source[folder_start:file_match.start()].rstrip()
    last_sep = max(prefix.rfind('\\'), prefix.rfind('/'))
    if last_sep >= 0:
        head = prefix[:last_sep + 1]
        tail = re.split(r"\s", prefix[last_sep + 1:], 1)[0]
        prefix = f"{head}{tail}"
    prefix = prefix.rstrip('\\/')
    filename = file_match.group(0).strip().strip('"').strip("'")
    separator = '\\' if '\\' in prefix else '/'
    return f"{prefix}{separator}{filename}"


def _extract_secondary_data_path(text: str, exclude: str | None = None) -> str | None:
    source = text or ''
    full_patterns = [
        r"[A-Za-z]:\\[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
        r"/[^\s\n\r\t\"']+?\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)",
    ]
    for pattern in full_patterns:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            candidate = match.group(0).strip().strip('"').strip("'")
            if exclude and candidate.lower() == exclude.lower():
                continue
            return candidate

    filename_pattern = r"[A-Za-z0-9À-ÿ._-]+\.(?:qgz|qgs|gpkg|xlsx|xlsm|xls|docx|odt|ods|pdf|csv|shp|geojson|kml|kmz|txt|md)"
    filename_matches = list(re.finditer(filename_pattern, source, flags=re.IGNORECASE))
    if not filename_matches:
        return None
    filename_match = filename_matches[-1]
    filename = filename_match.group(0).strip().strip('"').strip("'")
    if exclude and filename.lower() == exclude.lower():
        return None

    folder_starts = [m for m in re.finditer(r"[A-Za-z]:\\|/", source, flags=re.IGNORECASE) if m.start() < filename_match.start()]
    if not folder_starts:
        return filename
    folder_start = folder_starts[-1].start()
    prefix = source[folder_start:filename_match.start()].rstrip()
    last_sep = max(prefix.rfind('\\'), prefix.rfind('/'))
    if last_sep >= 0:
        head = prefix[:last_sep + 1]
        tail = re.split(r"\s", prefix[last_sep + 1:], 1)[0]
        prefix = f"{head}{tail}"
    prefix = prefix.rstrip('\\/')
    separator = '\\' if '\\' in prefix else '/'
    return f"{prefix}{separator}{filename}"


def _looks_like_executable_path(value: str) -> bool:
    candidate = (value or '').strip().lower()
    return bool(candidate) and candidate.endswith(('.exe', '.app', '.bat', '.cmd', '.com'))


def _looks_qgis_related(text: str) -> bool:
    haystack = (text or '').lower()
    qgis_keywords = (
        'qgis',
        'geo',
        'geodaten',
        'geodata',
        'karte',
        'kart',
        'shp',
        'shx',
        'dbf',
        'prj',
        'cpg',
        'gpkg',
        'geojson',
        'kml',
        'kmz',
        'qgz',
        'qgs',
        'layer',
        'map',
        'maps',
        'shapefile',
        'shape file',
        'shape-file',
    )
    return any(keyword in haystack for keyword in qgis_keywords)




def _parse_desktop_actions(reply_text: str) -> tuple[str, list[DesktopAction]]:
    payload = _extract_json_object(reply_text)
    if not payload:
        return reply_text, []
    reply = str(payload.get('reply') or '').strip()
    raw_actions = payload.get('desktop_actions') or []
    actions: list[DesktopAction] = []
    if isinstance(raw_actions, list):
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            try:
                actions.append(DesktopAction.model_validate(item))
            except Exception:
                continue
    return reply or reply_text, actions


@router.post('/', response_model=ChatResponse)
async def chat_enhanced(payload: ChatRequest, db: DbSession, current_user: User = Depends(get_current_user)) -> ChatResponse:
    current_user_id = int(current_user.id)
    rag_sources: list[dict[str, object]] = []
    resolved_project_id = payload.project_id
    if resolved_project_id is None and payload.conversation_id is not None:
        conv_result = await db.execute(select(Conversation.project_id).where(Conversation.id == payload.conversation_id))
        resolved_project_id = conv_result.scalar_one_or_none()
    # basic project permission checks
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

    chat_profile = None
    if resolved_profile_id is not None:
        chat_profile = await load_chat_profile(db, int(resolved_profile_id))
        if chat_profile is not None and chat_profile.project_id is not None and chat_profile.project_id != (conv_project.id if conv_project else chat_profile.project_id):
            raise HTTPException(status_code=403, detail='Profil gehört zu einem anderen Projekt.')
        if chat_profile is not None and chat_profile.owner_id not in {current_user_id, getattr(conv_project, 'owner_id', current_user_id)} and current_user.role != UserRole.ADMIN:
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
        stmt = insert(Conversation).values(title=None, project_id=conv_project.id if conv_project else None, profile_id=resolved_profile_id).returning(Conversation)
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
    if chat_profile is not None:
        profile_context = build_chat_profile_context(chat_profile, conv_project.name if conv_project else None)
        if profile_context:
            hippo_messages.append({"role": "system", "content": profile_context})
    if memory is not None:
        memory_context = build_conversation_memory_context(memory)
        if memory_context:
            hippo_messages.append({"role": "system", "content": memory_context})

    if payload.desktop_agent:
        profile = (payload.desktop_profile or 'generic').strip().lower()
        profile_label = {
            'generic': 'Allgemeiner Desktop-Agent',
            'qgis': 'QGIS-Workflow',
            'fledermaus': 'Fledermaus-Workflow',
            'bioacoustics': 'Fledermaus-/Akustik-Workflow',
            'custom': 'Benutzerdefinierter Workflow',
        }.get(profile, 'Allgemeiner Desktop-Agent')
        profile_details = {
            'generic': 'Nutze diesen Modus für allgemeine Desktop-Aufgaben. Wenn passende Programme gestartet werden sollen, verwende hipponalyze, QGIS, Word, Excel oder LibreOffice über launch_app oder open_file.',
            'qgis': (
                'Nutze QGIS für Karten, Layer, GeoPackages, Filter, Auswertungen und Exporte. '
                'Bei geographischen Beobachtungsdaten analysiere immer species by species, '
                'prüfe Koordinaten, Kontakthäufigkeit, Beobachtungsdaten und vorhandene Geo-Metadaten, '
                'erkenne Konzentrationen / Hotspots, leite mögliche Brutreviere oder Territorien ab, '
                'beziehe artspezifische Eigenschaften, Saison und Lebensraum mit ein und erweitere die Analyse '
                'bei Bedarf um weitere Kennzahlen, wenn der Benutzer mehr verlangt. '
                'Wenn der Nutzer einen Bericht in Word möchte, liefere die Analyse zunächst kompakt aus, erzeuge danach eine .docx-Datei und, falls sinnvoll, öffne sie per Word- oder LibreOffice-Preset.'
            ),
            'fledermaus': 'Nutze das Fledermaus-Programm für Lautdateien, Spektrogramme, Klassifikation und Auswertung.',
            'bioacoustics': 'Nutze das akustische Analyseprogramm für Bat-Calls, Spektrogramme und Bestimmung.',
            'custom': 'Folge der vom Benutzer beschriebenen Desktop-Routine und frage nach, wenn ein Schritt unsicher ist.',
        }.get(profile, 'Nutze diesen Modus für allgemeine Desktop-Aufgaben.')
        agent_sys = (
            "Desktop-Agent-Modus ist aktiv. Der Benutzer möchte Programme auf seinem PC steuern.\n"
            f"Profil: {profile_label}. {profile_details}\n"
            "Antworte in *gültigem JSON* und *nur* als JSON-Objekt ohne Markdown, ohne Codeblock und ohne Zusatztext.\n"
            "Schema:\n"
            "{\n"
            '  "reply": "kurze menschliche Erklärung",\n'
            '  "desktop_actions": [\n'
            "    {\n"
            '      "action": "launch|launch_app|open_file|command|key|type|click|scroll|move|wait",\n'
            '      "command": "...",\n'
            '      "args": "...",\n'
            '      "cwd": "...",\n'
            '      "app": "qgis|hipponalyze|word|excel|libreoffice",\n'
            '      "file": "...",\n'
            '      "keys": "...",\n'
            '      "text": "...",\n'
            '      "button": "1",\n'
            '      "x": 0,\n'
            '      "y": 0,\n'
            '      "direction": "up|down|left|right",\n'
            '      "amount": 1,\n'
            '      "wait_seconds": 1\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Regeln:\n"
            "- Nutze desktop_actions nur für echte PC-Steuerung.\n"
            "- Wenn der Benutzer einen QGIS-Workflow, eine Datei oder ein Projekt analysieren will, arbeite in dieser Reihenfolge: 1) passende App öffnen, 2) Datei/Projekt laden, 3) Analyse durchführen, 4) Ergebnis als Word-Report liefern.\n"
            "- Der Desktop-Agent hat Zugriff auf den Computer des Benutzers. Sage nicht, dass du keinen Zugriff auf lokale Dateien oder auf den Computer hast, wenn desktop_agent aktiv ist.\n"
            "- Wenn es um Projektdateien geht, verlange keinen Scan als Voraussetzung; nutze den vorhandenen Projektordner-Kontext oder frage den Desktop-Agenten nach einer direkten, kurzen Verzeichnisliste statt eines Tiefenscans.\n"
            "- Wenn ein Report oder eine Datei auf Inhalte aus dem Projekt basiert, nimm die aktiven Projekt-Skills und Projekt-Tools als Arbeitsanweisung ernst und lies die Inhalte der Dateien direkt, statt nur aus Metadaten zu antworten.\n"
            "- Wenn der Benutzer ausdrücklich einen Word-Bericht möchte, erzeuge bevorzugt eine .docx-Datei und ergänze sie mit klarer Zusammenfassung statt nur Text in der Chat-Antwort.\n"
            "- Wenn der Benutzer ein Bild verlangt, liefere einen einzigen Bild-Datei-Block und ändere die Bildbeschreibung nicht in zusätzlicher Prosa; der Client rendert die erzeugte Bilddatei unverändert.\n"
            "- Beim QGIS-Profil solltest du Geodaten immer artweise auswerten, Koordinaten und Kontakte prüfen, Cluster und mögliche Brutreviere erkennen und den Nutzer bei Bedarf nach weiteren Kennzahlen fragen.\n"
            "- Wenn der Benutzer eine QGIS-Datei, ein Shapefile, ein GeoPackage oder eine Projektdatei nennt, starte QGIS direkt mit dieser Datei und lade nicht zuerst einen generischen Viewer.\n"
            "- Halte reply kurz und sag, was du tust.\n"
            "- Wenn du mehr Kontext brauchst, lege mit reply eine Rückfrage und desktop_actions leer.\n"
            "- Wenn ein Schritt riskant oder unklar ist, frage statt zu raten.\n"
        )
        hippo_messages.insert(0, {"role": "system", "content": agent_sys})


    if conv_project is not None:
        project_sys = (
            "You are assisting a user within a project. The project may have local project folders where generated files are saved.\n"
            "If the user asks for a deliverable file (Word, PDF, image, SVG, report, exported document), return exactly one file block and no extra commentary.\n"
            "If the user only asks a question, wants an explanation, or wants a simple answer, respond as plain chat text and do not create a file.\n"
            "Use this format for files:\n"
            "<<<FILE:filename.ext>>>\n"
            "<file content here>\n"
            "<<<END_FILE>>>\n"
            "For .docx and .pdf, provide the final document text/content. For .svg, provide valid SVG markup. For raster images (.png/.jpg/.jpeg), provide a concise visual description or poster brief that should be rendered into the image.\n"
            "If the user explicitly requests an image or PNG, return a real file block with an image filename instead of prose instructions. If the user only wants analysis or a textual answer, respond in text and do not create an image file.\n"
            "If the user asks to analyze documents from the project folders, use the project context and answer in the user's language.\n"
            "If project_folder_context is present, treat it as the source of truth for the project folder contents and do not claim you lack local filesystem access.\n"
            "If the project has a saved local folder, do not say you cannot access it; use the project context or ask for a refresh instead.\n"
            "For project-folder questions, respond with a detailed structure: summary, analysis, conclusion. Use all available project folders by default and never ask the user to choose folders or files unless they explicitly narrow the scope.\n"
            "Write in a polished Claude-like style: direct, structured, concise but thorough, no preamble, no self-referential commentary, no repetitive reassurance, and minimize transitional phrases.\n"
            "Write the answer as a polished document with clear section headings and concise paragraphs. Prefer a three-part structure when possible: summary, analysis, conclusion. Avoid decorative Markdown around headings.\n"
            "If an image, screenshot, or document is attached, rely on the direct attachment data in the prompt and any locally extracted text; do not claim that you cannot read attachments.\n"
            "For SHP/SHX/DBF/PRJ/CPG data, interpret the geodata as ecological field data when appropriate and surface contact counts, seasonality, habitat clues, spatial clusters, species-specific patterns, and possible territories / breeding areas. If the user wants more depth, extend the analysis with additional metrics, maps, or statistical summaries.\n"
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
        try:
            if payload.project_folder_context and payload.project_folder_context.strip():
                project_context_parts.append(payload.project_folder_context.strip())
            if conv_project is not None:
                backend_project_context = await build_project_files_context(
                    conv_project,
                    include_previews=True,
                    question=payload.message,
                    source_prefixes=payload.project_source_prefixes,
                )
                if backend_project_context.strip():
                    project_context_parts.append(backend_project_context.strip())
            if not project_context_parts:
                project_context_parts.append(
                    "Der Desktop-Agent ist aktiv und kann den Computer bedienen. "
                    "Lokale Projektordner werden nicht dauerhaft tief gescannt; "
                    "wenn der Kontext noch leer ist, antworte ohne erfundene Dateinamen und fordere nur eine kurze direkte Ordnerauflistung an."
                )
            project_files_context = "\n\n".join(project_context_parts)
            hippo_messages.insert(
                3,
                {
                    "role": "system",
                    "content": (
                        "Kontext der lokalen Projektordner:\n"
                        f"{project_files_context}\n\n"
                        "Nutze diesen Kontext, wenn der Benutzer die Dateien oder den Ordner analysieren möchte, antworte ausführlich auf Deutsch und bleibe content-first: erst Inhalt, Extraktion und technische Schlussfolgerung, dann erst optional Dateinamen. Vermeide Tabellen oder übertriebenes Markdown.\n"
                        "Wenn der Benutzer einen Bericht, ein Word-Dokument oder einen PDF-Export aus dem Projektordner möchte, verwende automatisch alle verfügbaren Ordner und Dateien des Projekts, ohne nach bestimmten Dateien oder Unterordnern zu fragen, sofern der Benutzer die Auswahl nicht explizit einschränkt."
                    ),
                },
            )
        except Exception:
            pass

    recent_messages = messages[-18:]
    for m in recent_messages:
        role = 'user' if m.role == 'user' else 'assistant' if m.role == 'assistant' else 'system'
        hippo_messages.append({"role": role, "content": m.content})

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
        payload_h = {
            "model": model_name,
            "messages": hippo_messages,
            "temperature": 0.45 if (payload.attachments or conv_project is not None) else 0.7,
            "max_tokens": max_tokens,
        }
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
            r = await client.post(chat_api_url, json=payload_h, headers=headers)
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
            raise HTTPException(status_code=502, detail=f'Fehler der Hippo-API: {e}')

    # sanitize & store
    try:
        reply_text = re.sub(r"<think>[\s\S]*?<\/think>", "", reply_text, flags=re.IGNORECASE)
    except Exception:
        pass

    desktop_actions: list[DesktopAction] = []
    if payload.desktop_agent:
        parsed_reply, desktop_actions = _parse_desktop_actions(reply_text)
        reply_text = parsed_reply
    inferred_actions: list[DesktopAction] = []
    try:
        qgis_context = ' '.join(
            part for part in [
                payload.message or '',
                ' '.join(getattr(attachment, 'filename', '') for attachment in (payload.attachments or [])),
                reply_text or '',
            ]
            if part
        )
        if _looks_qgis_related(qgis_context) or (payload.desktop_profile or '').strip().lower() == 'qgis':
            inferred_actions = [
                DesktopAction.model_validate(action)
                for action in infer_desktop_launch_actions(qgis_context, reply_text, payload.desktop_profile)
                if isinstance(action, dict) and str(action.get('command') or '').strip().lower() == 'qgis'
            ]
    except Exception:
        inferred_actions = []
    if inferred_actions:
        existing = {
            json.dumps(action.model_dump(exclude_none=True), sort_keys=True, ensure_ascii=False)
            for action in desktop_actions
        }
        for action in inferred_actions:
            serialized = json.dumps(action.model_dump(exclude_none=True), sort_keys=True, ensure_ascii=False)
            if serialized not in existing:
                desktop_actions.append(action)
                existing.add(serialized)

    generated_files, cleaned_reply = extract_generated_files(reply_text)
    if cleaned_reply:
        reply_text = cleaned_reply
    serialized_files: list[dict[str, str]] = []
    for file in generated_files:
        try:
            data, mime_type, filename = build_generated_file_bytes_with_fallback(file.filename, file.content)
        except Exception:
            # Skip unsupported render targets instead of crashing the chat route.
            continue
        serialized_files.append(
            {
                "filename": filename,
                "mime_type": mime_type,
                "data_base64": base64.b64encode(data).decode("ascii"),
            }
        )

    await db.execute(insert(ChatMessage).values(conversation_id=conv_id, user_id=current_user_id, role='assistant', content=reply_text))
    await db.commit()

    try:
        await refresh_conversation_memory(
            db,
            conv_id,
            recent_messages=messages[-18:],
            assistant_reply=reply_text,
            project_name=conv_project.name if conv_project else None,
            profile_name=getattr(chat_profile, 'name', None),
        )
    except Exception:
        logger.warning("conversation memory update failed for conversation %s", conv_id)

    return ChatResponse(reply=reply_text, conversation_id=conv_id, generated_files=serialized_files, desktop_actions=desktop_actions)
