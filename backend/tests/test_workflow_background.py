from types import SimpleNamespace

from app.services.workflow_executor import execute_workflow_by_id


def test_execute_workflow_by_id_exists():
    assert callable(execute_workflow_by_id)
