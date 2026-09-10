from contextlib import suppress

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.services.database_bootstrap import ensure_database_schema_and_tables
from app.services.bootstrap import ensure_bootstrap_admin
from app.services.model_registry import sync_model_registry

app = FastAPI(
    title="HIPPO-AI API",
    version="0.1.0",
    description="Foundation API for HIPPO-AI.",
)

logger = logging.getLogger("hippo-ai.api")


async def _sync_model_registry_once() -> None:
    async with AsyncSessionLocal() as session:
        await sync_model_registry(session)


async def _sync_model_registry_forever() -> None:
    while True:
        try:
            await _sync_model_registry_once()
        except Exception as exc:
            logger.warning("Model registry sync failed: %s", exc)
        await asyncio.sleep(15 * 60)


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
    logger.info(
        "HIPPO AI backend starting | base_url=%s | model=%s | api_key_present=%s | vision_url=%s",
        settings.hippo_api_url,
        settings.hippo_model,
        bool((settings.hippo_api_key or '').strip()),
        settings.hippo_vision_url,
    )
    await ensure_database_schema_and_tables(engine)
    async with AsyncSessionLocal() as session:
        created = await ensure_bootstrap_admin(session)
        if created:
            logger.info("Bootstrap admin created: %s", settings.bootstrap_admin_email)
    try:
        await _sync_model_registry_once()
    except Exception as exc:
        logger.warning("Initial model registry sync failed: %s", exc)
    app.state.model_registry_task = asyncio.create_task(_sync_model_registry_forever())


@app.on_event("shutdown")
async def shutdown_model_registry_sync() -> None:
    logger.info("HIPPO AI backend shutting down")
    task = getattr(app.state, "model_registry_task", None)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hippo-ai-api"}


@app.get("/ready", tags=["system"])
async def ready() -> dict[str, str]:
    return {"status": "ready", "environment": settings.app_env}
