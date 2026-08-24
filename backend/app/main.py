from fastapi import FastAPI

from app.api.routes import api_router
from app.core.config import settings

app = FastAPI(
    title="HIPPO-AI API",
    version="0.1.0",
    description="Foundation API for HIPPO-AI.",
)

app.include_router(api_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hippo-ai-api"}


@app.get("/ready", tags=["system"])
async def ready() -> dict[str, str]:
    return {"status": "ready", "environment": settings.app_env}
