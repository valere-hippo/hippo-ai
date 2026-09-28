from __future__ import annotations

from datetime import datetime
from typing import Iterable


def _conversation_sort_key(conversation) -> tuple[datetime, int]:
    created_at = getattr(conversation, 'created_at', None)
    if not isinstance(created_at, datetime):
        created_at = datetime.min
    conversation_id = int(getattr(conversation, 'id', 0) or 0)
    return created_at, conversation_id


def choose_latest_project_conversation_id(conversations: Iterable[object], project_id: int | None) -> int | None:
    if project_id is None:
        return None

    latest = None
    latest_key: tuple[datetime, int] | None = None
    for conversation in conversations:
        if int(getattr(conversation, 'project_id', 0) or 0) != int(project_id):
            continue
        key = _conversation_sort_key(conversation)
        if latest is None or key > latest_key:
            latest = conversation
            latest_key = key

    return int(getattr(latest, 'id', 0) or 0) or None