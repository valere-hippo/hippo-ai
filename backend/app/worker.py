from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress

from app.db.session import AsyncSessionLocal
from app.services.workflow_executor import claim_next_queued_workflow, execute_workflow_by_id

logger = logging.getLogger("hippo-ai.workflow-worker")


async def run_worker(poll_interval_seconds: float = 3.0) -> None:
    stop_event = asyncio.Event()

    def _handle_stop(*_args):
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            signal.signal(sig, _handle_stop)

    logger.info("Workflow worker started | poll_interval=%.1fs", poll_interval_seconds)
    while not stop_event.is_set():
        workflow_id: int | None = None
        try:
            async with AsyncSessionLocal() as db:
                workflow_id = await claim_next_queued_workflow(db)
            if workflow_id is None:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass
                continue

            logger.info("Workflow worker picked up workflow %s", workflow_id)
            try:
                await execute_workflow_by_id(workflow_id)
                logger.info("Workflow worker completed workflow %s", workflow_id)
            except Exception as exc:
                logger.exception("Workflow worker failed for workflow %s: %s", workflow_id, exc)
        except Exception as exc:
            logger.exception("Workflow worker loop error: %s", exc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
            except asyncio.TimeoutError:
                pass

    logger.info("Workflow worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    asyncio.run(run_worker(float(os.getenv("HIPPO_WORKER_POLL_INTERVAL_SECONDS", "3"))))
