from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.conversation_threads import choose_latest_project_conversation_id, choose_project_conversation_id


def test_choose_latest_project_conversation_id_prefers_latest_for_project():
    base = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    conversations = [
        SimpleNamespace(id=11, project_id=7, created_at=base - timedelta(minutes=10)),
        SimpleNamespace(id=12, project_id=7, created_at=base - timedelta(minutes=1)),
        SimpleNamespace(id=21, project_id=8, created_at=base),
    ]

    assert choose_latest_project_conversation_id(conversations, 7) == 12


def test_choose_latest_project_conversation_id_returns_none_for_missing_project():
    conversations = [
        SimpleNamespace(id=11, project_id=7, created_at=datetime.now(timezone.utc)),
    ]

    assert choose_latest_project_conversation_id(conversations, 99) is None


def test_choose_project_conversation_id_prefers_existing_active_conversation():
    base = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    conversations = [
        SimpleNamespace(id=11, project_id=7, created_at=base - timedelta(minutes=10)),
        SimpleNamespace(id=12, project_id=7, created_at=base - timedelta(minutes=1)),
    ]

    assert choose_project_conversation_id(conversations, 7, 11) == 11
    assert choose_project_conversation_id(conversations, 7, 99) == 12


def test_choose_project_conversation_id_returns_none_for_missing_project():
    conversations = [
        SimpleNamespace(id=11, project_id=7, created_at=datetime.now(timezone.utc)),
    ]

    assert choose_project_conversation_id(conversations, 99) is None
