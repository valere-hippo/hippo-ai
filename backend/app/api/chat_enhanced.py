from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import re
from pathlib import Path
import logging
from app.api.dependencies import get_current_user, DbSession
from app.models.user import User
from app.models.chat import Conversation, ChatMessage
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

router = APIRouter(prefix="/chat-enhanced", tags=["chat"])
logger = logging.getLogger("hippo-ai.chat")

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
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


def _infer_generated_filename(message: str) -> str:
    text = (message or '').lower()
    if 'pdf' in text:
        return 'hippo-bericht.pdf'
    if any(token in text for token in ['svg', 'karte', 'map', 'diagramm', 'chart', 'grafik']):
        return 'hippo-bericht.svg'
    if any(token in text for token in ['png', 'jpg', 'jpeg', 'bild', 'image', 'foto']):
        return 'hippo-bericht.png'
    if 'rtf' in text:
        return 'hippo-bericht.rtf'
    return 'hippo-bericht.docx'




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


def _infer_desktop_launch_action(message: str, reply_text: str, profile: str | None = None) -> list[DesktopAction]:
    haystack = f"{message or ''}\n{reply_text or ''}".lower()
    if not any(keyword in haystack for keyword in ('öffne', 'oeffne', 'ouvrir', 'ouvre', 'ouvrir le', 'open', 'starte', 'start', 'launch', 'run', 'lance', 'lancer', 'charge', 'charger', 'öffnen', 'oeffnen', 'öffnest', 'öffnet', 'starten')):
        return []

    open_path = _extract_candidate_open_path(haystack)
    data_path = _extract_secondary_data_path(haystack, exclude=open_path)
    actions: list[DesktopAction] = []
    if open_path:
        if _looks_like_executable_path(open_path):
            app_key = 'qgis' if 'qgis' in haystack or profile == 'qgis' else 'word' if ('word' in haystack or 'bericht' in haystack or 'report' in haystack) else 'excel' if 'excel' in haystack else 'libreoffice' if ('libreoffice' in haystack or 'soffice' in haystack) else 'qgis'
            actions.append(DesktopAction(action='launch_app', command=app_key, path=open_path, file=data_path or None))
        elif 'qgis' in haystack or profile == 'qgis':
            actions.append(DesktopAction(action='launch_app', command='qgis', file=open_path))
        elif 'word' in haystack or 'bericht' in haystack or 'report' in haystack:
            actions.append(DesktopAction(action='launch_app', command='word', file=open_path))
        elif 'excel' in haystack:
            actions.append(DesktopAction(action='launch_app', command='excel', file=open_path))
        elif 'libreoffice' in haystack or 'soffice' in haystack:
            actions.append(DesktopAction(action='launch_app', command='libreoffice', file=open_path))
        else:
            actions.append(DesktopAction(action='open_file', file=open_path))
        return actions

    candidates: list[tuple[str, list[str]]] = [
        ('hipponalyze', ['hipponalyze', 'hippo analyze', 'hippo-analyze']),
        ('qgis', ['qgis']),
        ('word', ['word', 'microsoft word']),
        ('excel', ['excel', 'microsoft excel']),
        ('libreoffice', ['libreoffice', 'soffice']),
    ]
    for app_key, needles in candidates:
        if any(needle in haystack for needle in needles):
            return [DesktopAction(action='launch_app', command=app_key)]

    if profile == 'qgis' and ('karte' in haystack or 'geo' in haystack or 'gpkg' in haystack):
        return [DesktopAction(action='launch_app', command='qgis')]
    if profile in {'fledermaus', 'bioacoustics'} and any(needle in haystack for needle in ('fledermaus', 'bat', 'ruf', 'rufe', 'akustik')):
        return [DesktopAction(action='launch_app', command='hipponalyze')]

    return []


def _desktop_agent_off_reply(message: str, profile: str | None = None) -> str:
    profile_label = {
        'qgis': 'QGIS',
        'fledermaus': 'Fledermaus',
        'bioacoustics': 'Fledermaus-/Akustik',
        'custom': 'benutzerdefinierte Programme',
    }.get((profile or '').strip().lower(), 'Programme')
    return (
        f"PC-Agent ist aus. Schalte PC-Agent ein, dann kann ich {profile_label} auf deinem PC öffnen, klicken, tippen und steuern. "
        "Dann kann ich auch hipponalyze, QGIS, Word, Excel oder LibreOffice direkt bedienen."
    )


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

    if not payload.desktop_agent:
        inferred_launch_actions = _infer_desktop_launch_action(payload.message, payload.message, payload.desktop_profile)
        if inferred_launch_actions:
            reply_text = _desktop_agent_off_reply(payload.message, payload.desktop_profile)
            await db.execute(insert(ChatMessage).values(conversation_id=conv_id, user_id=current_user_id, role='assistant', content=reply_text))
            await db.commit()
            return ChatResponse(reply=reply_text, conversation_id=conv_id, generated_files=[], desktop_actions=[])

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
    hippo_messages.insert(0, {"role": "system", "content": build_hippo_system_prompt()})

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
            "- Wenn der Benutzer ein Programm starten will, verwende launch.\n"
            "- Wenn der Benutzer einen QGIS-Workflow, eine Datei oder ein Projekt analysieren will, arbeite in dieser Reihenfolge: 1) passende App öffnen, 2) Datei/Projekt laden, 3) Analyse durchführen, 4) Ergebnis als Word-Report liefern.\n"
            "- Wenn der Benutzer ausdrücklich einen Word-Bericht möchte, erzeuge bevorzugt eine .docx-Datei und ergänze sie mit klarer Zusammenfassung statt nur Text in der Chat-Antwort.\n"
            "- Beim QGIS-Profil solltest du Geodaten immer artweise auswerten, Koordinaten und Kontakte prüfen, Cluster und mögliche Brutreviere erkennen und den Nutzer bei Bedarf nach weiteren Kennzahlen fragen.\n"
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
            "For project-folder questions, respond with a detailed structure: overview, visible files, file-by-file details, and conclusion.\n"
            "Write the answer as a polished document with clear section headings, paragraphs, and bullets. Avoid decorative Markdown around headings.\n"
            "If an image, screenshot, or document is attached, rely on the direct attachment data in the prompt and any locally extracted text; do not claim that you cannot read attachments.\n"
            "For SHP/SHX/DBF/PRJ/CPG data, interpret the geodata as ecological field data when appropriate and surface contact counts, seasonality, habitat clues, spatial clusters, species-specific patterns, and possible territories / breeding areas. If the user wants more depth, extend the analysis with additional metrics, maps, or statistical summaries.\n"
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
            if payload.project_folder_context and payload.project_folder_context.strip():
                project_files_context = payload.project_folder_context.strip()
            elif conv_project is not None:
                project_files_context = await build_project_files_context(conv_project, include_previews=not looks_like_project_inventory_request(payload.message), question=payload.message, source_prefixes=payload.project_source_prefixes)
            else:
                project_files_context = (
                    "Kein lokaler Projektordner-Kontext vom Desktop erhalten. "
                    "Antworte nicht mit erfundenen Dateinamen und fordere bei Bedarf den Benutzer auf, den lokalen Ordner im Desktop zu verbinden."
                )
            hippo_messages.insert(
                3,
                {
                    "role": "system",
                    "content": (
                        "Kontext der lokalen Projektordner:\n"
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
                1 if conv_project is None else 4,
                {
                    "role": "system",
                    "content": (
                        f"{tools_context}\n\n"
                        "Diese Tools stehen dem Agenten zur Verfügung. Nutze sie als Arbeitsmittel und beschreibe danach klar die Ergebnisse."
                    ),
                },
            )
    except Exception:
        pass

    # call Hippo chat completions
    if not settings.hippo_api_url:
        raise HTTPException(status_code=503, detail="Die Hippo-API ist nicht konfiguriert. Bitte HIPPO_AI_BASE_URL und HIPPO_AI_MODEL setzen.")

    direct_project_reply = None
    if conv_project is not None and looks_like_project_inventory_request(payload.message):
        direct_project_reply = project_files_context.strip()

    if direct_project_reply:
        reply_text = direct_project_reply
    else:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {"Content-Type": "application/json"}
            if settings.hippo_api_key:
                headers["Authorization"] = f"Bearer {settings.hippo_api_key}"
            model_name = settings.hippo_model
            max_tokens = await resolve_chat_max_tokens(db, settings.hippo_response_max_tokens, settings.hippo_response_max_tokens_long)
            if payload.attachments or conv_project is not None:
                max_tokens = max(512, min(max_tokens, settings.hippo_response_max_tokens_long))
            payload_h = {
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
                r = await client.post(settings.hippo_api_url.rstrip('/') + '/v1/chat/completions', json=payload_h, headers=headers)
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
        if not desktop_actions:
            desktop_actions = _infer_desktop_launch_action(payload.message, reply_text, payload.desktop_profile)

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
            # Skip unsupported render targets instead of crashing the chat route.
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

    await db.execute(insert(ChatMessage).values(conversation_id=conv_id, user_id=current_user_id, role='assistant', content=reply_text))
    await db.commit()

    return ChatResponse(reply=reply_text, conversation_id=conv_id, generated_files=serialized_files, desktop_actions=desktop_actions)
