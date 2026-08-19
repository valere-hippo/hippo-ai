from __future__ import annotations

import dataclasses
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .remote_clients import OpenAICompatibleChatClient
from .retrieval import RetrievalFilter, RetrievalHit, RetrievalSearchSummary, search_project


DEFAULT_CHAT_MODEL = "Qwen3-30B-A3B-Instruct-2507"
CHAT_HISTORY_FILE = "history.json"
GENERAL_CHAT_FILE = "general.json"


@dataclass(slots=True)
class ChatSource:
    id: str
    title: str
    relative_path: str
    source_path: str
    file_name: str
    extension: str
    category: str
    species: str | None = None
    observed_at: str | None = None
    zone: str | None = None
    geometry_type: str | None = None
    score: float = 0.0
    snippet: str = ""


@dataclass(slots=True)
class ChatResponse:
    project_id: str
    project_slug: str
    question: str
    answer: str
    backend: str
    index_path: str
    model_name: str
    total_candidates: int
    returned_hits: int
    citations: list[str] = field(default_factory=list)
    sources: list[ChatSource] = field(default_factory=list)
    created_at: str = ""


@dataclass(slots=True)
class GeneralChatResponse:
    question: str
    answer: str
    backend: str
    model_name: str
    created_at: str


def answer_project_question(
    *,
    project_id: str,
    project_slug: str,
    question: str,
    index_root: Path,
    project_data_root: Path | None = None,
    history_root: Path | None = None,
    filters: RetrievalFilter | None = None,
    prefer_real_models: bool = True,
    max_sources: int = 6,
) -> ChatResponse:
    search, sources = prepare_project_question(
        project_id=project_id,
        project_slug=project_slug,
        question=question,
        index_root=index_root,
        filters=filters,
        prefer_real_models=prefer_real_models,
        max_sources=max_sources,
    )
    model_name = _chat_model_name()
    backend = _chat_backend_name()
    answer, citations = _generate_answer(
        question=question,
        search=search,
        sources=sources,
        prefer_real_models=prefer_real_models,
    )
    response = ChatResponse(
        project_id=project_id,
        project_slug=project_slug,
        question=question,
        answer=answer,
        backend=backend,
        index_path=search.index_path,
        model_name=model_name,
        total_candidates=search.total_candidates,
        returned_hits=search.returned_hits,
        citations=citations,
        sources=sources,
        created_at=_now_iso(),
    )
    _persist_project_chat_turn(
        project_data_root=project_data_root,
        question=question,
        response=response,
    )
    return response


def answer_general_question(
    *,
    question: str,
    history_root: Path | None = None,
    prefer_real_models: bool = True,
) -> GeneralChatResponse:
    answer = _generate_general_answer(question=question, prefer_real_models=prefer_real_models)
    response = GeneralChatResponse(
        question=question,
        answer=answer,
        backend=_chat_backend_name(),
        model_name=_chat_model_name(),
        created_at=_now_iso(),
    )
    _persist_general_chat_turn(
        history_root=history_root,
        question=question,
        response=response,
    )
    return response


def prepare_project_question(
    *,
    project_id: str,
    project_slug: str,
    question: str,
    index_root: Path,
    filters: RetrievalFilter | None = None,
    prefer_real_models: bool = True,
    max_sources: int = 6,
) -> tuple[RetrievalSearchSummary, list[ChatSource]]:
    filters = filters or RetrievalFilter(limit=max_sources)
    search = search_project(
        project_id=project_id,
        project_slug=project_slug,
        query=question,
        index_root=index_root,
        filters=dataclasses.replace(filters, limit=max_sources),
        prefer_real_models=prefer_real_models,
    )
    sources = _sources_from_hits(search.hits[:max_sources])
    return search, sources


def stream_general_question(
    *,
    question: str,
    history_root: Path | None = None,
    prefer_real_models: bool = True,
) -> Iterator[dict[str, Any]]:
    yield {
        "type": "meta",
        "backend": _chat_backend_name(),
        "model_name": _chat_model_name(),
        "sources": [],
    }

    answer = _generate_general_answer(question=question, prefer_real_models=prefer_real_models)
    emitted = False
    for chunk in _chunk_text(answer):
        emitted = True
        yield {"type": "delta", "delta": chunk}
    if not emitted:
        yield {"type": "delta", "delta": answer}

    response = GeneralChatResponse(
        question=question,
        answer=answer,
        backend=_chat_backend_name(),
        model_name=_chat_model_name(),
        created_at=_now_iso(),
    )
    _persist_general_chat_turn(
        history_root=history_root,
        question=question,
        response=response,
    )
    yield {"type": "final", "response": dataclasses.asdict(response)}


def stream_project_question(
    *,
    project_id: str,
    project_slug: str,
    question: str,
    index_root: Path,
    project_data_root: Path | None = None,
    filters: RetrievalFilter | None = None,
    prefer_real_models: bool = True,
    max_sources: int = 6,
) -> Iterator[dict[str, Any]]:
    search, sources = prepare_project_question(
        project_id=project_id,
        project_slug=project_slug,
        question=question,
        index_root=index_root,
        filters=filters,
        prefer_real_models=prefer_real_models,
        max_sources=max_sources,
    )

    yield {
        "type": "meta",
        "project_id": project_id,
        "project_slug": project_slug,
        "backend": search.backend,
        "index_path": search.index_path,
        "total_candidates": search.total_candidates,
        "returned_hits": search.returned_hits,
        "sources": [dataclasses.asdict(source) for source in sources],
    }

    answer, citations = _generate_answer(
        question=question,
        search=search,
        sources=sources,
        prefer_real_models=prefer_real_models,
    )
    emitted = False
    for chunk in _chunk_text(answer):
        emitted = True
        yield {"type": "delta", "delta": chunk}
    if not emitted:
        yield {"type": "delta", "delta": answer}

    response = ChatResponse(
        project_id=project_id,
        project_slug=project_slug,
        question=question,
        answer=answer,
        backend=_chat_backend_name(),
        index_path=search.index_path,
        model_name=_chat_model_name(),
        total_candidates=search.total_candidates,
        returned_hits=search.returned_hits,
        citations=citations,
        sources=sources,
        created_at=_now_iso(),
    )
    _persist_project_chat_turn(
        project_data_root=project_data_root,
        question=question,
        response=response,
    )
    yield {"type": "final", "response": to_dict(response)}


def _generate_general_answer(*, question: str, prefer_real_models: bool) -> str:
    client = _chat_client(prefer_real_models=prefer_real_models)
    if client is None:
        return _fallback_general_answer(question)

    messages = [
        {
            "role": "system",
            "content": (
                "Du bist hippo-ai, ein pragmatischer Assistent für Projektarbeit, Geo-Daten und Berichte. "
                "Antworte auf Deutsch, klar und direkt. Wenn Kontext fehlt, frage nach statt etwas zu erfinden."
            ),
        },
        {
            "role": "user",
            "content": question,
        },
    ]
    try:
        return client.chat(messages, temperature=0.2).strip() or _fallback_general_answer(question)
    except Exception:
        return _fallback_general_answer(question)


def _fallback_general_answer(question: str) -> str:
    return (
        f"Frage: {question}\n\n"
        "Ich bin im allgemeinen Modus. Für projektbezogene Auswertungen wähle links ein Projekt aus. "
        "Für Dateianalysen, Berichte und Quellenbezug arbeite ich dann direkt mit dem Projektkontext."
    )


def to_dict(response: ChatResponse) -> dict[str, Any]:
    payload = dataclasses.asdict(response)
    return payload


def load_chat_history(history_path: Path) -> list[dict[str, Any]]:
    if not history_path.exists():
        return []
    try:
        loaded = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return loaded if isinstance(loaded, list) else []


def _generate_answer(
    *,
    question: str,
    search: RetrievalSearchSummary,
    sources: list[ChatSource],
    prefer_real_models: bool,
) -> tuple[str, list[str]]:
    if not sources:
        return (
            "Ich habe keine ausreichenden Quellen gefunden. Bitte lade das Projektverzeichnis zuerst in den Index "
            "und prüfe anschließend die Frage erneut.",
            [],
        )

    context = _build_source_context(question, search, sources)
    client = _chat_client(prefer_real_models=prefer_real_models)
    if client is None:
        return _fallback_answer(question, search, sources)

    messages = [
        {
            "role": "system",
            "content": (
                "Du bist hippo-ai, ein fachlicher Projektassistent für Geo-, Arten- und Berichtsdaten. "
                "Antworte auf Deutsch, präzise und professionell. "
                "Nutze nur die gelieferten Quellen und markiere Quellen in deinem Text mit [S1], [S2] usw. "
                "Wenn die Beweislage dünn ist, sage das offen. "
                "Gib deine Antwort als JSON mit den Schlüsseln answer und citations zurück."
            ),
        },
        {
            "role": "user",
            "content": context,
        },
    ]
    try:
        raw = client.chat(messages, temperature=0.2)
        parsed = _parse_response_json(raw)
        answer = str(parsed.get("answer") or "").strip()
        if not answer:
            answer = raw.strip()
        citations = _normalize_citations(parsed.get("citations"), sources)
        if not citations:
            citations = _citations_from_text(answer, sources)
        if not citations:
            citations = [source.id for source in sources[: min(3, len(sources))]]
        return answer, citations
    except Exception:
        return _fallback_answer(question, search, sources)


def _fallback_answer(question: str, search: RetrievalSearchSummary, sources: list[ChatSource]) -> tuple[str, list[str]]:
    top_sources = sources[: min(3, len(sources))]
    citations = [source.id for source in top_sources]
    lines = [
        f"Frage: {question}",
        "",
        f"Ich habe {search.returned_hits} relevante Quellen in {search.backend}-Index gefunden.",
        "Die stärksten Belege sind:",
    ]
    for source in top_sources:
        label = _source_label(source)
        snippet = source.snippet.strip()
        if snippet:
            lines.append(f"- [{source.id}] {label}: {snippet}")
        else:
            lines.append(f"- [{source.id}] {label}")
    lines.append("")
    lines.append("Bitte die relevanten Stellen im Projektkontext fachlich prüfen.")
    return "\n".join(lines), citations


def _build_source_context(question: str, search: RetrievalSearchSummary, sources: list[ChatSource]) -> str:
    source_lines = []
    for source in sources:
        meta = ", ".join(
            part
            for part in [
                f"Art={source.species}" if source.species else None,
                f"Datum={source.observed_at}" if source.observed_at else None,
                f"Zone={source.zone}" if source.zone else None,
                f"Kategorie={source.category}" if source.category else None,
            ]
            if part
        )
        source_lines.append(
            "\n".join(
                [
                    f"[{source.id}] {source.title}",
                    f"Pfad: {source.relative_path}",
                    f"Metadaten: {meta or 'ohne'}",
                    f"Auszug: {source.snippet or '(kein Auszug)'}",
                ]
            )
        )

    return "\n\n".join(
        [
            f"Projekt: {search.project_slug}",
            f"Frage: {question}",
            "",
            "Quellen:",
            *source_lines,
            "",
            "Aufgabe: Antworte fachlich, benutze nur diese Quellen und zitiere sie inline mit den Quellenkennungen.",
            "Antworte als JSON mit den Schlüsseln answer und citations.",
        ]
    )


def _sources_from_hits(hits: list[RetrievalHit]) -> list[ChatSource]:
    sources: list[ChatSource] = []
    for index, hit in enumerate(hits, start=1):
        sources.append(
            ChatSource(
                id=f"S{index}",
                title=hit.title,
                relative_path=hit.relative_path,
                source_path=hit.source_path,
                file_name=hit.file_name,
                extension=hit.extension,
                category=hit.category,
                species=hit.species,
                observed_at=hit.observed_at,
                zone=hit.zone,
                geometry_type=hit.geometry_type,
                score=float(hit.score),
                snippet=hit.snippet,
            )
        )
    return sources


def _persist_project_chat_turn(
    *,
    project_data_root: Path | None,
    question: str,
    response: ChatResponse,
) -> None:
    if project_data_root is None:
        return
    history_path = Path(project_data_root).joinpath("chat", CHAT_HISTORY_FILE)
    _append_chat_turn(
        history_path,
        question=question,
        answer=response.answer,
        created_at=response.created_at,
        backend=response.backend,
        model_name=response.model_name,
        citations=response.citations,
        sources=[dataclasses.asdict(source) for source in response.sources],
        project_id=response.project_id,
        project_slug=response.project_slug,
    )


def _persist_general_chat_turn(
    *,
    history_root: Path | None,
    question: str,
    response: GeneralChatResponse,
) -> None:
    if history_root is None:
        return
    history_path = Path(history_root).joinpath("chat", GENERAL_CHAT_FILE)
    _append_chat_turn(
        history_path,
        question=question,
        answer=response.answer,
        created_at=response.created_at,
        backend=response.backend,
        model_name=response.model_name,
        citations=[],
        sources=[],
        project_id="general",
        project_slug="general",
    )


def _append_chat_turn(
    history_path: Path,
    *,
    question: str,
    answer: str,
    created_at: str,
    backend: str,
    model_name: str,
    citations: list[str],
    sources: list[dict[str, Any]],
    project_id: str,
    project_slug: str,
) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    messages = load_chat_history(history_path)
    messages.append(
        {
            "role": "user",
            "content": question,
            "created_at": created_at,
        }
    )
    messages.append(
        {
            "role": "assistant",
            "content": answer,
            "created_at": created_at,
            "backend": backend,
            "model_name": model_name,
            "citations": citations,
            "sources": sources,
            "project_id": project_id,
            "project_slug": project_slug,
            "streaming": False,
        }
    )
    history_path.write_text(json.dumps(messages, indent=2, ensure_ascii=False), encoding="utf-8")


def _chunk_text(text: str, *, chunk_size: int = 120) -> list[str]:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return []
    chunks: list[str] = []
    current = ""
    for part in re.split(r"(?<=[.!?])\s+", normalized):
        candidate = f"{current} {part}".strip() if current else part
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(part) > chunk_size:
            chunks.append(part[:chunk_size])
            part = part[chunk_size:]
        current = part
    if current:
        chunks.append(current)
    return chunks


def _chat_client(prefer_real_models: bool = True) -> OpenAICompatibleChatClient | None:
    mode = _model_mode()
    remote_url = _remote_chat_url()
    if not remote_url:
        if mode == "remote":
            raise RuntimeError("HIPPO_AI_LLM_URL is not configured while HIPPO_AI_MODEL_MODE=remote")
        return None
    return OpenAICompatibleChatClient(
        base_url=remote_url,
        model_name=_chat_model_name(),
        api_key=_remote_chat_api_key(),
        timeout=_remote_timeout_seconds(),
    )


def _chat_backend_name() -> str:
    if _remote_chat_url():
        return "remote"
    if _model_mode() == "remote":
        return "remote"
    return "local"


def _parse_response_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return {}
    return {}


def _normalize_citations(raw_citations: Any, sources: list[ChatSource]) -> list[str]:
    valid_ids = {source.id for source in sources}
    if isinstance(raw_citations, list):
        return [str(item) for item in raw_citations if str(item) in valid_ids]
    if isinstance(raw_citations, str) and raw_citations in valid_ids:
        return [raw_citations]
    return []


def _citations_from_text(text: str, sources: list[ChatSource]) -> list[str]:
    ids = {source.id for source in sources}
    found = []
    for source_id in ids:
        if f"[{source_id}]" in text or source_id in text:
            found.append(source_id)
    return sorted(found)


def _source_label(source: ChatSource) -> str:
    bits = [source.title]
    if source.species:
        bits.append(source.species)
    if source.relative_path:
        bits.append(source.relative_path)
    return " · ".join(bits)


def _remote_chat_url() -> str | None:
    value = os.getenv("HIPPO_AI_LLM_URL") or os.getenv("HIPPO_AI_CHAT_URL")
    if value:
        return value
    return None


def _remote_chat_api_key() -> str | None:
    return os.getenv("HIPPO_AI_LLM_API_KEY") or os.getenv("HIPPO_AI_REMOTE_API_KEY")


def _remote_timeout_seconds() -> int:
    raw = os.getenv("HIPPO_AI_REMOTE_TIMEOUT_SECONDS") or "60"
    try:
        return max(1, int(raw))
    except ValueError:
        return 60


def _chat_model_name() -> str:
    return os.getenv("HIPPO_AI_LLM_MODEL") or DEFAULT_CHAT_MODEL


def _model_mode() -> str:
    raw = os.getenv("HIPPO_AI_MODEL_MODE") or "auto"
    mode = raw.strip().lower()
    if mode in {"remote", "auto", "local"}:
        return mode
    return "auto"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
