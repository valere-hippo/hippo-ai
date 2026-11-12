from __future__ import annotations

from typing import Any

from sqlalchemy import insert, select

from app.models.chat import Conversation
from app.models.permission import PermissionLevel
from app.models.project import Project
from app.models.workflow import AIWorkflow, AIWorkflowTask
from app.services.permissions import has_project_permission
from app.services.workflow_planner import build_workflow_metadata, has_workflow_markers


async def ensure_workflow_for_message(
    db,
    *,
    current_user,
    conversation_id: int | None,
    project_id: int | None,
    source_message: str,
    metadata: dict[str, Any] | None = None,
    final_model_tag: str | None = None,
) -> dict[str, Any] | None:
    text = (source_message or "").strip()
    if not text or not has_workflow_markers(text):
        return None

    plan = build_workflow_metadata(text, final_model_tag=final_model_tag, default_model_tag="openai")
    tasks = plan.get("tasks") or []
    if not tasks:
        return None

    project = None
    if project_id is not None:
        project_res = await db.execute(select(Project).where(Project.id == project_id))
        project = project_res.scalar_one_or_none()
        if project is None:
            return None
        allowed = await has_project_permission(db, current_user, project, PermissionLevel.READ)
        if not allowed:
            return None

    if conversation_id is not None:
        conv_res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conversation = conv_res.scalar_one_or_none()
        if conversation is None:
            return None
        if project_id is not None and conversation.project_id not in (None, project_id):
            return None

    workflow_stmt = insert(AIWorkflow).values(
        conversation_id=conversation_id,
        project_id=project_id,
        created_by_user_id=int(current_user.id),
        source_message=text,
        status=plan["status"],
        final_model_tag=plan["final_model_tag"],
        workflow_metadata=metadata or {"source": "auto", "plan": plan},
    ).returning(AIWorkflow)
    result = await db.execute(workflow_stmt)
    workflow = result.scalar_one()

    task_rows = []
    for task in tasks:
        task_rows.append(
            {
                "workflow_id": workflow.id,
                "task_key": task["task_key"],
                "title": task["title"],
                "instruction": task["instruction"],
                "model_tag": task["model_tag"],
                "input_kind": task["input_kind"],
                "execution_mode": task["execution_mode"],
                "depends_on": task["depends_on"],
                "status": "pending",
                "sort_order": task["sort_order"],
            }
        )
    if task_rows:
        await db.execute(insert(AIWorkflowTask), task_rows)
    await db.commit()
    return {
        "workflow_id": workflow.id,
        "status": plan["status"],
        "final_model_tag": plan["final_model_tag"],
        "tasks": tasks,
    }
