import asyncio
from datetime import datetime
from types import SimpleNamespace

import app.services.workflow_executor as workflow_executor


class _Result:
    def __init__(self, workflow):
        self._workflow = workflow

    def scalar_one_or_none(self):
        return self._workflow


class _FakeDB:
    def __init__(self, workflow):
        self.workflow = workflow
        self.commits = 0

    async def execute(self, stmt):
        return _Result(self.workflow)

    async def commit(self):
        self.commits += 1


async def _call_queue(workflow):
    db = _FakeDB(workflow)
    await workflow_executor.queue_workflow_execution(db, workflow.id)
    return db


async def _call_claim(workflow):
    db = _FakeDB(workflow)
    workflow.status = 'queued'
    workflow.updated_at = datetime.utcnow()
    await workflow_executor.claim_next_queued_workflow(db)
    return db


def test_queue_workflow_execution_marks_workflow_queued():
    workflow = SimpleNamespace(id=11, status='pending', updated_at=datetime(2024, 1, 1))
    db = asyncio.run(_call_queue(workflow))

    assert workflow.status == 'queued'
    assert db.commits == 1


def test_claim_next_queued_workflow_marks_running():
    workflow = SimpleNamespace(id=11, status='queued', updated_at=datetime(2024, 1, 1), created_at=datetime(2024, 1, 1))
    db = __import__('asyncio').run(_call_claim(workflow))

    assert workflow.status == 'running'
    assert db.commits == 1
