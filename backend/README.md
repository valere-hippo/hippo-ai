# hippo-ai backend

Phase-0 backend für Projektverwaltung, Authentifizierung, Audit-Logging und Backups.

## Lokaler Start

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Umgebungsvariablen

- `HIPPO_AI_ADMIN_USER`
- `HIPPO_AI_ADMIN_PASSWORD`
- `HIPPO_AI_JWT_SECRET`
- `HIPPO_AI_DATA_ROOT`

