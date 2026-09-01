import asyncio

from app.services import embedding_context as ec


def test_search_embedding_context_prefers_remote_results(monkeypatch):
    calls: list[str] = []

    async def fake_remote(query: str, project_id: int, limit: int):
        calls.append("remote")
        return [{"id": 1, "text": "Grünlandkartierung Arte", "score": 0.97, "metadata": {"source": "store"}}]

    async def fake_local(db, query: str, project_id=None, limit: int = 5):
        calls.append("local")
        return []

    monkeypatch.setattr(ec, "_search_remote_embedding_context", fake_remote)
    monkeypatch.setattr(ec, "_search_local_embedding_context", fake_local)

    result = asyncio.run(ec.search_embedding_context(object(), "Kannst du nochmal suchen?", project_id=12, limit=5))

    assert result and result[0]["text"] == "Grünlandkartierung Arte"
    assert calls == ["remote"]


def test_search_embedding_context_falls_back_to_local_results(monkeypatch):
    calls: list[str] = []

    async def fake_remote(query: str, project_id: int, limit: int):
        calls.append("remote")
        return []

    async def fake_local(db, query: str, project_id=None, limit: int = 5):
        calls.append("local")
        return [{"id": 2, "text": "Lokaler Projekt-Hinweis", "score": 0.81, "metadata": {"source": "db"}}]

    monkeypatch.setattr(ec, "_search_remote_embedding_context", fake_remote)
    monkeypatch.setattr(ec, "_search_local_embedding_context", fake_local)

    result = asyncio.run(ec.search_embedding_context(object(), "Kannst du nochmal suchen?", project_id=12, limit=5))

    assert result and result[0]["text"] == "Lokaler Projekt-Hinweis"
    assert calls == ["remote", "local"]


def test_build_embedding_context_for_request_returns_empty_without_project():
    result = asyncio.run(ec.build_embedding_context_for_request(object(), "irrelevant", project_id=None, limit=5))
    assert result == ""
