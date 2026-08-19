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

## Retrieval

Der Backend-Service stellt zusätzlich Projekt-Retrieval-Endpunkte bereit:

- `POST /projects/{project_id}/retrieval/index`
- `POST /projects/{project_id}/retrieval/search`

Diese Endpunkte nutzen `BGE-M3` für Embeddings, `bge-reranker-v2-m3` für das
Re-Ranking und speichern optional in Qdrant.
