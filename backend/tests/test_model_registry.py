import asyncio
from types import SimpleNamespace

from app.services import model_registry as mr


def test_extract_model_entries_supports_openai_shape():
    payload = {"object": "list", "data": [{"id": "hippo-ai"}, {"id": "hippo-vision"}]}

    entries = mr._extract_model_entries(payload)

    assert [item["id"] for item in entries] == ["hippo-ai", "hippo-vision"]


def test_normalize_model_row_maps_common_fields():
    source = mr.ModelRegistrySource(provider="chat", source_url="https://example.test", api_key="secret", capability="chat")
    row = mr._normalize_model_row(
        source,
        {
            "id": "hippo-ai",
            "display_name": "Hippo AI",
            "context_length": 8192,
            "max_tokens": 2048,
        },
        "https://example.test",
    )

    assert row["provider"] == "chat"
    assert row["model_id"] == "hippo-ai"
    assert row["display_name"] == "Hippo AI"
    assert row["context_window"] == 8192
    assert row["max_output_tokens"] == 2048


def test_resolve_chat_model_name_uses_fallback_when_registry_empty(monkeypatch):
    async def fake_get_latest_model(db, provider):
        return None

    monkeypatch.setattr(mr, "get_latest_model", fake_get_latest_model)

    result = asyncio.run(mr.resolve_chat_model_name(object(), "hippo-ai"))

    assert result == "hippo-ai"


def test_resolve_chat_max_tokens_uses_cached_limits(monkeypatch):
    async def fake_get_latest_model(db, provider):
        return SimpleNamespace(status="ok", max_output_tokens=3000, context_window=5000)

    monkeypatch.setattr(mr, "get_latest_model", fake_get_latest_model)

    result = asyncio.run(mr.resolve_chat_max_tokens(object(), 4096, 8192))

    assert result == 3000
