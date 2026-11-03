from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import insert, select, update

from app.core.config import settings
from app.models.chat import ChatMessage
from app.models.conversation_memory import ConversationMemory
from app.models.user import User

logger = logging.getLogger("hippo-ai.conversation-memory")


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


def _extract_json_object(text: str) -> dict[str, Any] | None:
    source = (text or "").strip()
    if not source:
        return None
    if source.startswith("{") and source.endswith("}"):
        try:
            parsed = json.loads(source)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    start = source.find("{")
    end = source.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(source[start:end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


async def load_conversation_memory(db: Any, conversation_id: int) -> ConversationMemory | None:
    result = await db.execute(select(ConversationMemory).where(ConversationMemory.conversation_id == conversation_id))
    return result.scalar_one_or_none()


def build_conversation_memory_context(memory: ConversationMemory | None) -> str:
    if memory is None:
        return ""

    parts = ["Dauerhafter Kontext dieser Unterhaltung:"]
    if memory.summary_text:
        parts.append("- Zusammenfassung:")
        parts.extend([f"  {line}" for line in memory.summary_text.splitlines() if line.strip()])
    if memory.facts_text:
        parts.append("- Stabile Fakten / Entscheidungen:")
        parts.extend([f"  {line}" for line in memory.facts_text.splitlines() if line.strip()])
    return "\n".join(parts)


async def _upsert_conversation_memory(
    db: Any,
    conversation_id: int,
    summary_text: str,
    facts_text: str,
) -> None:
    existing = await load_conversation_memory(db, conversation_id)
    if existing is None:
        await db.execute(
            insert(ConversationMemory).values(
                conversation_id=conversation_id,
                summary_text=summary_text or None,
                facts_text=facts_text or None,
                updated_at=datetime.utcnow(),
            )
        )
    else:
        await db.execute(
            update(ConversationMemory)
            .where(ConversationMemory.conversation_id == conversation_id)
            .values(
                summary_text=summary_text or None,
                facts_text=facts_text or None,
                updated_at=datetime.utcnow(),
            )
        )
    await db.commit()


async def refresh_conversation_memory(
    db: Any,
    conversation_id: int,
    recent_messages: list[ChatMessage],
    assistant_reply: str,
    project_name: str | None = None,
    profile_name: str | None = None,
) -> None:
    if not recent_messages and not assistant_reply.strip():
        return

    if not settings.hippo_api_url:
        return

    chat_api_url = _normalize_chat_base_url(settings.hippo_api_url)
    if not chat_api_url:
        return

    existing_memory = await load_conversation_memory(db, conversation_id)
    recent_excerpt = recent_messages[-18:]
    transcript_lines: list[str] = []
    for message in recent_excerpt:
        role = 'user' if message.role == 'user' else 'assistant' if message.role == 'assistant' else 'system'
        transcript_lines.append(f"{role}: {message.content}")
    if assistant_reply.strip():
        transcript_lines.append(f"assistant: {assistant_reply.strip()}")

    system_prompt = (
        "Du verwaltest eine dauerhafte Erinnerung für genau eine Unterhaltung.\n"
        "Ziel: Die Erinnerung muss Monate später noch reichen, um den Chatkontext wiederherzustellen.\n"
        "Regeln:\n"
        "- Bewahre nur stabile Fakten, Entscheidungen, Präferenzen, offene Aufgaben und wichtige Projektkontexte.\n"
        "- Mische keine Informationen aus anderen Unterhaltungen hinein.\n"
        "- Entferne vergängliche oder triviale Details.\n"
        "- Wenn etwas neu oder geändert ist, aktualisiere die Erinnerung entsprechend.\n"
        "- Antworte ausschließlich als gültiges JSON-Objekt ohne Markdown und ohne Zusatztext.\n"
        "Schema:\n"
        '{"summary_text":"kurze fortlaufende Zusammenfassung","facts_text":"stabile Fakten und Entscheidungen als Zeilenblock"}'
    )

    memory_context: list[str] = []
    if project_name:
        memory_context.append(f"Projekt: {project_name}")
    if profile_name:
        memory_context.append(f"Profil: {profile_name}")
    if existing_memory and existing_memory.summary_text:
        memory_context.append("Bisherige Zusammenfassung:")
        memory_context.append(existing_memory.summary_text.strip())
    if existing_memory and existing_memory.facts_text:
        memory_context.append("Bisherige stabile Fakten:")
        memory_context.append(existing_memory.facts_text.strip())

    user_prompt = "\n".join(
        [
            "Aktualisiere die dauerhafte Unterhaltungserinnerung anhand des folgenden Gesprächsauszugs.",
            *memory_context,
            "Gesprächsauszugs:",
            *transcript_lines,
        ]
    )

    headers = {"Content-Type": "application/json"}
    if settings.hippo_api_key:
        headers["Authorization"] = f"Bearer {settings.hippo_api_key}"

    payload = {
        "model": settings.hippo_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 320,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10.0)) as client:
            response = await client.post(chat_api_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("choices"):
                content = data["choices"][0]["message"]["content"]
            else:
                content = str(data)
    except Exception as exc:
        logger.warning("conversation memory refresh failed for conversation %s: %s", conversation_id, exc)
        return

    parsed = _extract_json_object(content)
    if not parsed:
        return

    summary_text = str(parsed.get("summary_text") or parsed.get("summary") or "").strip()
    facts_text = str(parsed.get("facts_text") or parsed.get("facts") or "").strip()
    if not summary_text and not facts_text:
        return

    await _upsert_conversation_memory(db, conversation_id, summary_text, facts_text)
