import asyncio
from types import SimpleNamespace

from app.services import embedding_context as ec
from app.services.project_skills import format_project_skills_context


def test_format_project_skills_context_includes_shared_and_project_skills():
    skills = [
        SimpleNamespace(name="Shared", description="Global", instructions="Do global", is_enabled=True, project_id=None),
        SimpleNamespace(name="Project", description="Local", instructions="Do local", is_enabled=True, project_id=12),
        SimpleNamespace(name="Off", description="Ignored", instructions="Ignore", is_enabled=False, project_id=None),
    ]

    result = format_project_skills_context(skills)

    assert "Aktive Projektskills und geteilte Skills" in result
    assert "Shared" in result
    assert "Project" in result
    assert "Off" not in result


def test_search_embedding_context_prefers_local_results(monkeypatch):
    calls: list[str] = []

    async def fake_remote(query: str, project_id: int, limit: int):
        calls.append("remote")
        return [{"id": 1, "text": "Remote result", "score": 0.97, "metadata": {"source": "store"}}]

    async def fake_local(db, query: str, project_id=None, limit: int = 5):
        calls.append("local")
        return []

    monkeypatch.setattr(ec, "_search_remote_embedding_context", fake_remote)
    monkeypatch.setattr(ec, "_search_local_embedding_context", fake_local)

    result = asyncio.run(ec.search_embedding_context(object(), "Kannst du nochmal suchen?", project_id=12, limit=5))

    assert result and result[0]["text"] == "Remote result"
    assert calls == ["local", "remote"]


def test_search_embedding_context_returns_local_results_without_remote(monkeypatch):
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
    assert calls == ["local"]


def test_build_embedding_context_for_request_returns_shared_results_without_project(monkeypatch):
    async def fake_search(db, query: str, project_id=None, limit: int = 5):
        assert project_id is None
        return [{"id": 9, "text": "Gemeinsame Wissensbasis", "score": 0.88, "metadata": {"source": "shared"}}]

    monkeypatch.setattr(ec, "search_embedding_context", fake_search)

    result = asyncio.run(ec.build_embedding_context_for_request(object(), "irrelevant", project_id=None, limit=5))

    assert "Geteilte Hinweise aus dem Embedding-Store" in result
    assert "Gemeinsame Wissensbasis" in result
