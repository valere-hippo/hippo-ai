from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import re
from pathlib import Path
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
    derive_conversation_title,
    looks_like_image_analysis_request,
    looks_like_geodata_visual_request,
    looks_like_image_generation_request,
)
from app.services.generated_files import GeneratedFile, build_generated_file_bytes_with_fallback, extract_generated_files
from app.services.project_tools import build_tools_context
from app.services.vision_analysis import build_vision_enriched_text
from app.services.project_skills import build_project_skills_context, build_shared_skills_context
from app.services.project_storage import build_geodata_map_file, build_project_files_context
import base64
import json

router = APIRouter(prefix="/chat-enhanced", tags=["chat-enhanced"]) 

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    project_id: int | None = None
    message: str
    attachments: list[ChatAttachment] | None = None
    desktop_agent: bool = False
    desktop_profile: str | None = None
    desktop_result: str | None = None


class DesktopAction(BaseModel):
    action: str
    command: str | None = None
    args: str | None = None
    cwd: str | None = None
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

    stored_message_content = await build_vision_enriched_text(payload.message, payload.attachments)
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

    if payload.attachments:
        hippo_messages[-1]["content"] = stored_message_content

    # global system prompt
    global_sys = (
        "Du bist HIPPO AI, ein freundlicher und professioneller KI-Assistent.\n"
        "HIPPO AI wurde für die Firma Hipposideros entwickelt.\n"
        "Unternehmensdaten von Hipposideros:\n"
        "- Inhaber: Oliver Meier-Ronfeld\n"
        "- Gegründet: 2010\n"
        "- Sitz: 53547 Breitscheid\n"
        "- Team: 6 Mitarbeitende + 4 freie Mitarbeiter:innen\n"
        "- Einsatzgebiet: Deutschland & Luxemburg\n"
        "- Rechtsform: Einzelunternehmer\n"
        "- Projekte erfasst: 90+ (2024–2026)\n"
        "- Schwerpunkt: Artenschutz & Chiroptera\n"
        "Valère Youbi ist der Entwickler von HIPPO AI. Nenne ihn nur, wenn nach der Entwicklung von HIPPO AI gefragt wird.\n"
        "Antworte in der Sprache des Benutzers.\n"
        "Antworte so ausführlich wie nötig, wenn der Benutzer eine detaillierte Erklärung, einen Bericht oder eine Analyse möchte.\n"
        "Kürze nur, wenn der Benutzer ausdrücklich eine kurze Antwort verlangt.\n"
        "Wenn eine Antwort lang sein muss, entwickle sie vollständig aus und schließe alle wichtigen Punkte ab.\n"
        "Nutze projektspezifisches Wissen, falls vorhanden, und verbinde es mit deinem Modellwissen zu einer einzigen, klaren Antwort.\n"
        "Wenn Bilder, Screenshots oder Dokumente angehängt sind, nutze die vom Vision-Modell gelieferten Beschreibungen und die lokal extrahierten Textdaten im Prompt und sage nicht, dass du Anhänge nicht lesen kannst.\n"
        "Bilder werden vorab vom Vision-Modell analysiert. Nutze diese Beschreibung direkt und stütze dich nicht nur auf OCR, Dateiname oder Metadaten.\n"
        "Wenn der Benutzer ein Bild nur beschreiben, zusammenfassen oder analysieren möchte, antworte als Text im Chat. Erzeuge nur dann eine Datei, wenn ausdrücklich ein Dateiformat verlangt wird.\n"
        "Wenn eine Datei, ein Bild oder der gemeinsame Projektordner analysiert wird, antworte ausführlich, strukturiert und mit klaren Zwischenüberschriften oder Aufzählungspunkten.\n"
        "Wenn der Benutzer ausdrücklich ein Bild, ein PNG oder eine Grafik generieren möchte, liefere einen echten Dateiblock mit einem Bilddateinamen und keine Anleitung zur manuellen Erstellung.\n"
        "Bei Geodatenpaketen aus SHP, SHX, DBF, PRJ oder CPG: analysiere die Kontakte je Art, nenne Kontaktzahl, Beobachtungszeitraum, räumliche Konzentration und mögliche ökologische Hinweise. Wenn sinnvoll, erstelle zusätzlich eine kleine Karte oder ein Diagramm als Datei.\n"
        "Bei Ordneranalysen liefere zuerst den Überblick, dann die sichtbaren Dateien, dann eine Detailanalyse pro Datei und am Ende ein kurzes Fazit.\n"
        "Schreibe Berichte mit sauberen Überschriften, Absätzen und Listen. Vermeide dekorative Markdown-Formate wie ###** oder **###.\n"
        "Nutze Tabellen nur, wenn sie wirklich klarer sind als Listen.\n"
    )
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
            'generic': 'Nutze diesen Modus für allgemeine Desktop-Aufgaben.',
            'qgis': (
                'Nutze QGIS für Karten, Layer, GeoPackages, Filter, Auswertungen und Exporte. ' 
                'Bei geographischen Beobachtungsdaten analysiere immer species by species, ' 
                'prüfe Koordinaten, Kontakthäufigkeit, Beobachtungsdaten und vorhandene Geo-Metadaten, ' 
                'erkenne Konzentrationen / Hotspots, leite mögliche Brutreviere oder Territorien ab, ' 
                'beziehe artspezifische Eigenschaften, Saison und Lebensraum mit ein und erweitere die Analyse ' 
                'bei Bedarf um weitere Kennzahlen, wenn der Benutzer mehr verlangt.'
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
            '      "action": "launch|command|key|type|click|scroll|move|wait",\n'
            '      "command": "...",\n'
            '      "args": "...",\n'
            '      "cwd": "...",\n'
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
            "- Wenn eine GUI bedient werden muss, plane mehrere kleine Aktionen statt einer großen.\n"
            "- Für QGIS, Desktop-Programme und Dateibrowser darfst du launch, click, key und type kombinieren.\n"
            "- Beim QGIS-Profil solltest du Geodaten immer artweise auswerten, Koordinaten und Kontakte prüfen, Cluster und mögliche Brutreviere erkennen und den Nutzer bei Bedarf nach weiteren Kennzahlen fragen.\n"
            "- Halte reply kurz und sag, was du tust.\n"
            "- Wenn du mehr Kontext brauchst, lege mit reply eine Rückfrage und desktop_actions leer.\n"
            "- Wenn ein Schritt riskant oder unklar ist, frage statt zu raten.\n"
        )
        hippo_messages.insert(0, {"role": "system", "content": agent_sys})


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
            "If the user explicitly requests an image or PNG, return a real file block with an image filename instead of prose instructions. If the user only wants analysis or a textual answer, respond in text and do not create an image file.\n"
            "If the user asks to analyze documents from the shared folder, use the project context and answer in the user's language.\n"
            "For shared-folder questions, respond with a detailed structure: overview, visible files, file-by-file details, and conclusion.\n"
            "Write the answer as a polished document with clear section headings, paragraphs, and bullets. Avoid decorative Markdown around headings.\n"
            "If an image, screenshot, or document is attached, rely on the supplied vision summary and any locally extracted text; do not claim that you cannot read attachments.\n"
            "For SHP/SHX/DBF/PRJ/CPG data, interpret the geodata as ecological field data when appropriate and surface contact counts, seasonality, habitat clues, spatial clusters, species-specific patterns, and possible territories / breeding areas. If the user wants more depth, extend the analysis with additional metrics, maps, or statistical summaries.\n"
            f"{build_attachment_response_guidance()}"
        )
        hippo_messages.insert(1, {"role": "system", "content": project_sys})

        try:
            if conv_project is not None:
                project_skills_context = await build_project_skills_context(db, conv_project.id, payload.message, limit=5)
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
            project_files_context = await build_project_files_context(conv_project)
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
        tools_context = await build_tools_context(db, payload.message, limit=6)
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

    async with httpx.AsyncClient(timeout=60.0) as client:
        headers = {"Content-Type": "application/json"}
        if settings.hippo_api_key:
            headers["Authorization"] = f"Bearer {settings.hippo_api_key}"
        model_name = settings.hippo_model
        max_tokens = settings.hippo_response_max_tokens
        if payload.attachments or conv_project is not None:
            max_tokens = min(settings.hippo_response_max_tokens_long, max(max_tokens, 512))
        payload_h = {
            "model": model_name,
            "messages": hippo_messages,
            "temperature": 0.45 if (payload.attachments or conv_project is not None) else 0.7,
            "max_tokens": max_tokens,
        }
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

    generated_files, cleaned_reply = extract_generated_files(reply_text)
    image_request = looks_like_image_generation_request(payload.message, payload.attachments)
    geodata_visual_request = looks_like_geodata_visual_request(payload.message, payload.attachments)
    geodata_direct_svg: tuple[str, str] | None = None

    if image_request and conv_project is not None and geodata_visual_request:
        geodata_file = build_geodata_map_file(conv_project, payload.message)
        if geodata_file:
            generated_files = [GeneratedFile(filename=geodata_file[0], content=geodata_file[1])]
            geodata_direct_svg = geodata_file

    has_image_attachment = any((getattr(att, 'mime_type', '') or '').lower().startswith('image/') for att in (payload.attachments or []))
    discarded_visual = False
    if has_image_attachment and not image_request and looks_like_image_analysis_request(payload.message, payload.attachments):
        if generated_files:
            discarded_visual = True
        generated_files = []

    if image_request and generated_files:
        normalized_files: list[GeneratedFile] = []
        for file in generated_files:
            suffix = Path(file.filename).suffix.lower()
            if geodata_direct_svg and file.filename == geodata_direct_svg[0]:
                normalized_files.append(file)
                continue
            if suffix in {".svg", ".png", ".jpg", ".jpeg"}:
                safe_stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(file.filename).stem).strip("_").lower() or "hippo_image"
                content = file.content
                if suffix == ".svg" and not file.content.lstrip().startswith("<svg"):
                    content = cleaned_reply or reply_text or payload.message
                normalized_files.append(GeneratedFile(filename=f"{safe_stem}.png", content=content))
            else:
                normalized_files.append(file)
        generated_files = normalized_files
    used_image_fallback = False
    if not generated_files and image_request:
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
