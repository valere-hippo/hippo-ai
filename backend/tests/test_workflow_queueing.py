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


class _FakeSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


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


async def _call_claim_specific(workflow):
    db = _FakeDB(workflow)
    workflow.status = 'queued'
    workflow.updated_at = datetime.utcnow()
    claimed = await workflow_executor.claim_workflow_if_queued(db, workflow.id)
    return db, claimed


def test_queue_workflow_execution_marks_workflow_queued():
    workflow = SimpleNamespace(id=11, status='pending', updated_at=datetime(2024, 1, 1))
    db = asyncio.run(_call_queue(workflow))

    assert workflow.status == 'queued'
    assert db.commits == 1


def test_claim_next_queued_workflow_marks_running():
    workflow = SimpleNamespace(id=11, status='queued', updated_at=datetime(2024, 1, 1), created_at=datetime(2024, 1, 1))
    db = asyncio.run(_call_claim(workflow))

    assert workflow.status == 'running'
    assert db.commits == 1


def test_claim_workflow_if_queued_only_claims_queued_workflows():
    workflow = SimpleNamespace(id=12, status='queued', updated_at=datetime(2024, 1, 1))
    db, claimed = asyncio.run(_call_claim_specific(workflow))

    assert claimed is True
    assert workflow.status == 'running'
    assert db.commits == 1


def test_execute_workflow_by_id_if_queued_runs_only_when_claimed():
    workflow = SimpleNamespace(id=13, status='queued', updated_at=datetime(2024, 1, 1))
    db = _FakeDB(workflow)
    executed = []

    async def fake_execute_workflow(db_arg, workflow_id):
        executed.append(workflow_id)
        return {'workflow_id': workflow_id, 'status': 'completed', 'results': {}}

    async def fake_persist(db_arg, workflow_id, result):
        executed.append(('persist', workflow_id, result['status']))

    original_session_local = workflow_executor.AsyncSessionLocal
    original_execute_workflow = workflow_executor.execute_workflow
    original_persist = workflow_executor._persist_workflow_result_message
    try:
        workflow_executor.AsyncSessionLocal = lambda: _FakeSessionContext(db)
        workflow_executor.execute_workflow = fake_execute_workflow
        workflow_executor._persist_workflow_result_message = fake_persist
        result = asyncio.run(workflow_executor.execute_workflow_by_id_if_queued(workflow.id))
    finally:
        workflow_executor.AsyncSessionLocal = original_session_local
        workflow_executor.execute_workflow = original_execute_workflow
        workflow_executor._persist_workflow_result_message = original_persist

    assert result is not None
    assert result['status'] == 'completed'
    assert executed == [13, ('persist', 13, 'completed')]
