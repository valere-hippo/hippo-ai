from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.services.database_bootstrap import ensure_database_schema_and_tables
from app.services.bootstrap import ensure_bootstrap_admin

app = FastAPI(
    title="HIPPO-AI API",
    version="0.1.0",
    description="Foundation API for HIPPO-AI.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
async def bootstrap_database_and_default_admin() -> None:
    await ensure_database_schema_and_tables(engine)
    async with AsyncSessionLocal() as session:
        created = await ensure_bootstrap_admin(session)
        if created:
            print(f"Bootstrap admin created: {settings.bootstrap_admin_email}")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hippo-ai-api"}


@app.get("/ready", tags=["system"])
async def ready() -> dict[str, str]:
    return {"status": "ready", "environment": settings.app_env}
