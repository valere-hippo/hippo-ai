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
