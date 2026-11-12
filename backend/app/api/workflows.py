from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import insert, select

from app.api.dependencies import DbSession, get_current_user
from app.models.chat import Conversation
from app.models.permission import PermissionLevel
from app.models.project import Project
from app.models.workflow import AIWorkflow, AIWorkflowTask
from app.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowPlanRequest,
    WorkflowPlanResponse,
    WorkflowResponse,
    WorkflowTaskCreatePreview,
    WorkflowTaskResponse,
)
from app.services.permissions import has_project_permission
from app.services.workflow_planner import build_workflow_metadata
from app.services.workflow_executor import execute_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


async def _load_project_if_needed(db: DbSession, project_id: int | None) -> Project | None:
    if project_id is None:
        return None
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekt nicht gefunden.")
    return project


async def _load_conversation_if_needed(db: DbSession, conversation_id: int | None) -> Conversation | None:
    if conversation_id is None:
        return None
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konversation nicht gefunden.")
    return conversation


async def _assert_project_access(db: DbSession, current_user, project: Project | None) -> None:
    if project is None:
        return
    allowed = await has_project_permission(db, current_user, project, PermissionLevel.READ)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Zugriff verweigert.")


def _serialize_task(task: AIWorkflowTask) -> WorkflowTaskResponse:
    return WorkflowTaskResponse.model_validate(task)


async def _load_workflow_with_tasks(db: DbSession, workflow_id: int) -> WorkflowResponse:
    workflow_res = await db.execute(select(AIWorkflow).where(AIWorkflow.id == workflow_id))
    workflow = workflow_res.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow nicht gefunden.")
    tasks_res = await db.execute(
        select(AIWorkflowTask)
        .where(AIWorkflowTask.workflow_id == workflow_id)
        .order_by(AIWorkflowTask.sort_order.asc(), AIWorkflowTask.id.asc())
    )
    tasks = [_serialize_task(task) for task in tasks_res.scalars().all()]
    payload = WorkflowResponse.model_validate(workflow)
    return payload.model_copy(update={"tasks": tasks})


@router.post("/plan", response_model=WorkflowPlanResponse)
async def plan_workflow(payload: WorkflowPlanRequest, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project_if_needed(db, payload.project_id)
    await _assert_project_access(db, current_user, project)
    conversation = await _load_conversation_if_needed(db, payload.conversation_id)
    conversation_project_id = conversation.project_id if conversation is not None else None
    if conversation is not None and payload.project_id is not None and conversation_project_id not in (None, payload.project_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Konversation und Projekt passen nicht zusammen.")

    plan = build_workflow_metadata(
        payload.source_message,
        final_model_tag=payload.final_model_tag,
        default_model_tag="openai",
    )
    tasks = [WorkflowTaskCreatePreview(**task) for task in plan["tasks"]]
    return WorkflowPlanResponse(workflow=None, tasks=tasks)


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(payload: WorkflowCreateRequest, db: DbSession, current_user=Depends(get_current_user)):
    project = await _load_project_if_needed(db, payload.project_id)
    await _assert_project_access(db, current_user, project)
    conversation = await _load_conversation_if_needed(db, payload.conversation_id)
    conversation_project_id = conversation.project_id if conversation is not None else None
    if conversation is not None and payload.project_id is not None and conversation_project_id not in (None, payload.project_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Konversation und Projekt passen nicht zusammen.")

    plan = build_workflow_metadata(
        payload.source_message,
        final_model_tag=payload.final_model_tag,
        default_model_tag="openai",
    )
    workflow_stmt = insert(AIWorkflow).values(
        conversation_id=payload.conversation_id,
        project_id=payload.project_id,
        created_by_user_id=int(current_user.id),
        source_message=payload.source_message.strip(),
        status=plan["status"],
        final_model_tag=plan["final_model_tag"],
        workflow_metadata=payload.metadata or None,
    ).returning(AIWorkflow)
    result = await db.execute(workflow_stmt)
    workflow = result.scalar_one()

    task_rows = []
    for task in plan["tasks"]:
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
    return await _load_workflow_with_tasks(db, workflow.id)


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(
    db: DbSession,
    conversation_id: int | None = None,
    project_id: int | None = None,
    current_user=Depends(get_current_user),
):
    project = await _load_project_if_needed(db, project_id)
    await _assert_project_access(db, current_user, project)
    if conversation_id is not None:
        conversation = await _load_conversation_if_needed(db, conversation_id)
        if project_id is not None and conversation.project_id not in (None, project_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Konversation und Projekt passen nicht zusammen.")

    stmt = select(AIWorkflow).order_by(AIWorkflow.created_at.desc())
    if conversation_id is not None:
        stmt = stmt.where(AIWorkflow.conversation_id == conversation_id)
    if project_id is not None:
        stmt = stmt.where(AIWorkflow.project_id == project_id)
    result = await db.execute(stmt)
    workflows = result.scalars().all()
    return [await _load_workflow_with_tasks(db, workflow.id) for workflow in workflows]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: int, db: DbSession, current_user=Depends(get_current_user)):
    workflow_res = await db.execute(select(AIWorkflow).where(AIWorkflow.id == workflow_id))
    workflow = workflow_res.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow nicht gefunden.")
    project = await _load_project_if_needed(db, workflow.project_id)
    await _assert_project_access(db, current_user, project)
    return await _load_workflow_with_tasks(db, workflow_id)


@router.post("/{workflow_id}/execute")
async def run_workflow(workflow_id: int, db: DbSession, current_user=Depends(get_current_user)):
    workflow_res = await db.execute(select(AIWorkflow).where(AIWorkflow.id == workflow_id))
    workflow = workflow_res.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow nicht gefunden.")
    project = await _load_project_if_needed(db, workflow.project_id)
    await _assert_project_access(db, current_user, project)
    return await execute_workflow(db, workflow_id)
