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
3. Run:

```bash
docker compose up --build
```

4. Apply database migrations:

```bash
docker compose exec api alembic upgrade head
```

5. API:
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

CI / SSH deploy
- The CI builds images and pushes to ghcr.io/${OWNER}/hippo-ai-api and hippo-ai-desktop. The CI deploy job SSHes to your host and runs the deploy script.
- Required repository secrets for CI deployment:
  - GHCR_TOKEN (GitHub PAT with packages:write)
  - DEPLOY_HOST, DEPLOY_USER, DEPLOY_SSH_KEY, DEPLOY_PATH, DEPLOY_PORT (optional)

Notes
- For GPU inference using vLLM/Whisper: provision hosts with NVIDIA drivers and nvidia-container-toolkit. Configure model volumes under /models.
- Backup Postgres and rotate secrets regularly.
