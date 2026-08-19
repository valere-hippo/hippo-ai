# hippo-ai backend

Phase-0 backend für Projektverwaltung, Authentifizierung, Audit-Logging und Backups.

## Lokaler Start

```bash
cd /pfad/zum/repo
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

## Umgebungsvariablen

- `HIPPO_AI_ADMIN_USER`
- `HIPPO_AI_ADMIN_PASSWORD`
- `HIPPO_AI_JWT_SECRET`
- `HIPPO_AI_DATA_ROOT`
- `HIPPO_AI_QDRANT_URL`
- `HIPPO_AI_QDRANT_PATH`
- `HIPPO_AI_EMBEDDING_URL`
- `HIPPO_AI_EMBEDDING_MODEL`
- `HIPPO_AI_RERANKER_URL`
- `HIPPO_AI_RERANKER_MODEL`
- `HIPPO_AI_LLM_URL`
- `HIPPO_AI_LLM_MODEL`
- `HIPPO_AI_REMOTE_TIMEOUT_SECONDS`

## Retrieval

Der Backend-Service stellt zusätzlich Projekt-Retrieval-Endpunkte bereit:

- `POST /projects/{project_id}/retrieval/index`
- `POST /projects/{project_id}/retrieval/search`
- `POST /projects/{project_id}/chat`

Diese Endpunkte nutzen `BGE-M3` für Embeddings, `bge-reranker-v2-m3` für das
Re-Ranking und speichern optional in Qdrant. Wenn die GPU-Hub-Variablen gesetzt
sind, ruft der Backend-Service die Modelle über OpenAI-kompatible HTTP-Endpoints
ab:

- `POST /v1/embeddings`
- `POST /v1/rerank`
- `POST /v1/chat/completions`

Damit kann `hippo-ai` die Modelle extern beziehen, während Qdrant und die
Projektlogik lokal oder auf dem Backend-Server laufen.

## Projekt-Chat

Der Chat-Endpunkt beantwortet Fragen auf Basis des aktiven Projektindex und
liefert die zugehörigen Quellen mit. Die Antwort wird bewusst auf Deutsch
erzeugt und soll inhaltlich nur die geladenen Projektquellen verwenden.
