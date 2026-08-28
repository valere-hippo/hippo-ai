from fastapi import FastAPI

from app.api.routes import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.bootstrap import ensure_bootstrap_admin

app = FastAPI(
    title="HIPPO-AI API",
    version="0.1.0",
    description="Foundation API for HIPPO-AI.",
)

app.include_router(api_router)


@app.on_event("startup")
async def bootstrap_default_admin() -> None:
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
