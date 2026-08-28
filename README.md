# HIPPO-AI — Phase 1 Foundation

Foundation for HIPPO-AI:
- FastAPI backend
- PostgreSQL
- Redis
- Docker Compose
- JWT authentication
- Users and roles
- Projects foundation
- Health/readiness endpoints

## Phase 1.1

Implemented:
- PostgreSQL + SQLAlchemy async
- User model
- ADMIN / MANAGER / USER / READ_ONLY roles
- Argon2 password hashing
- JWT access token
- Register / Login / Current user
- Alembic migration

## Start

1. Copy `.env.example` to `.env`
2. Set a strong `JWT_SECRET_KEY`
3. Optionally set `POSTGRES_SCHEMA=hippoai` if you want to override the default database schema name.
4. Optionally override the bootstrap admin defaults with `bootstrap_admin_full_name`, `bootstrap_admin_email`, and `bootstrap_admin_password`.
5. Run:

```bash
docker compose up --build
```

6. Apply database migrations:

```bash
docker compose exec api alembic upgrade head
```

7. API:
- http://localhost:8000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Important

Phase 1 deliberately does not implement AI/GPU workloads yet.
Those will be added behind stable interfaces in later phases.

## Deployment (Docker Compose)

We no longer use Kubernetes for Phase 1/2 deployments. Use the provided docker-compose.prod.yml for production deployments.

Quick steps:
1. Copy `.env.example` to `.env` and fill secrets (POSTGRES_PASSWORD, JWT_SECRET_KEY, etc.).
2. Ensure host has Docker, docker-compose, and (if using GPU models) nvidia-container-toolkit installed.
3. Copy `docker-compose.prod.yml` to the deployment host (e.g., `/opt/hippo-ai/docker-compose.yml`) and create the `.env` there.
4. Start services:

```bash
cd /opt/hippo-ai
docker compose pull
docker compose up -d --remove-orphans
```

CI / infra deploy
- The CI builds the API image and pushes it to ghcr.io/${OWNER}/hippo-ai-api.
- Required repository secrets for the build workflow:
  - GHCR_TOKEN (GitHub PAT with packages:write)
- On `hippo-ai`, the workflow now only builds and pushes from `master`.
- Deployment is handled from `hippoject-infra` on the Hetzner self-hosted runner using `AI_DEPLOY_PATH`.

Desktop installers
- The desktop installer workflow builds Windows `.exe` and macOS `.dmg` artifacts.
- Set `HIPPO_API_URL` in the repository or organization secrets to point the packaged app to production, for example `https://hippo-api.hipposideros-cloud.de`.
- If `HIPPO_API_URL` is missing, the desktop app falls back to `http://localhost:8000` for local development builds.

Notes
- For GPU inference using vLLM: provision hosts with NVIDIA drivers and nvidia-container-toolkit. Configure model volumes under /models.
- Voice dictation uses the local backend STT pipeline (`faster-whisper`). The backend image is pinned to Python 3.12 so PyAV can install cleanly. Tune it with `STT_MODEL`, `STT_DEVICE`, `STT_COMPUTE_TYPE`, and `STT_LANGUAGE` in `.env`.
- Hippo response length is intentionally generous by default. Tune `HIPPO_RESPONSE_MAX_TOKENS` and `HIPPO_RESPONSE_MAX_TOKENS_LONG` in `.env` if you want even longer answers for normal chats and project/file analyses.
- Hippo now extracts text locally from screenshots, images, PDFs, DOCX, and plain-text files before sending the prompt to `HIPPO_MODEL`. You do not need `HIPPO_VISION_MODEL` for normal attachment reading.
- Backup Postgres and rotate secrets regularly.
