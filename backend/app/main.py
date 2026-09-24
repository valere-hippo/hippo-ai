from contextlib import suppress

import asyncio
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
LOG_FILE_PATH = Path(os.getenv("HIPPO_LOG_FILE", "/app/logs/hippo-ai.log"))


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    stream_handler = None
    for handler in root.handlers:
        if getattr(handler, "_hippo_ai_stream", False):
            stream_handler = handler
            break
    if stream_handler is None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler._hippo_ai_stream = True  # type: ignore[attr-defined]
        root.addHandler(stream_handler)
    stream_handler.setFormatter(formatter)

    try:
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = None
        for handler in root.handlers:
            if getattr(handler, "baseFilename", None) == str(LOG_FILE_PATH):
                file_handler = handler
                break
        if file_handler is None:
            file_handler = RotatingFileHandler(LOG_FILE_PATH, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
            root.addHandler(file_handler)
        file_handler.setFormatter(formatter)
    except Exception as exc:
        root.warning("File logging disabled: %s", exc)


configure_logging()


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
