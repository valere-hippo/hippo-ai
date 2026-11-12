from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncio
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import AIWorkflow, AIWorkflowTask
from app.services.provider_clients import build_chat_completion_payload, build_provider_headers, resolve_provider_runtime


async def _load_workflow_tasks(db: AsyncSession, workflow_id: int) -> list[AIWorkflowTask]:
    result = await db.execute(
        select(AIWorkflowTask)
        .where(AIWorkflowTask.workflow_id == workflow_id)
        .order_by(AIWorkflowTask.sort_order.asc(), AIWorkflowTask.id.asc())
    )
    return result.scalars().all()


def _task_lookup(tasks: list[AIWorkflowTask]) -> dict[str, AIWorkflowTask]:
    return {task.task_key: task for task in tasks}


def _task_ready(task: AIWorkflowTask, tasks_by_key: dict[str, AIWorkflowTask]) -> bool:
    deps = list(task.depends_on or [])
    if not deps:
        return True
    return all(tasks_by_key.get(dep) and tasks_by_key[dep].status == "done" for dep in deps)


def _build_task_messages(workflow: AIWorkflow, task: AIWorkflowTask, dependency_texts: list[str]) -> list[dict[str, str]]:
    context_bits = [
        f"Workflow-ID: {workflow.id}",
        f"Task-Key: {task.task_key}",
        f"Task-Titel: {task.title}",
        f"Input-Kind: {task.input_kind}",
        f"Execution-Mode: {task.execution_mode}",
        f"Aufgabe: {task.instruction}",
    ]
    if dependency_texts:
        context_bits.append("Abhängigkeiten:")
        context_bits.extend(f"- {text}" for text in dependency_texts)
    system_prompt = (
        "Du bist ein spezialisiertes Teilmodell innerhalb eines Multi-Provider-Workflows. "
        "Bearbeite nur die zugewiesene Teilaufgabe und liefere eine klare, fachlich dichte Antwort. "
        "Antworte auf Deutsch, sofern die Aufgabe nicht explizit eine andere Sprache verlangt. "
        "Wenn die Aufgabe auf Dateien, Bilder oder Geodaten verweist, arbeite mit den übergebenen Inhalten und erkläre die wichtigsten Befunde. "
        "Wenn du unsicher bist, schreibe die Unsicherheit explizit in die Antwort."
    )
    user_prompt = "\n".join(context_bits)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _call_provider(task: AIWorkflowTask, workflow: AIWorkflow, dependency_texts: list[str]) -> dict[str, Any]:
    runtime = resolve_provider_runtime(task.model_tag)
    if not runtime.api_url:
        raise RuntimeError(f"Kein API-URL für Provider {runtime.tag} konfiguriert.")
    headers = build_provider_headers(runtime.api_key)
    messages = _build_task_messages(workflow, task, dependency_texts)
    payload = build_chat_completion_payload(runtime.model_name, messages, max_tokens=4096, temperature=0.25)
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
        response = await client.post(f"{runtime.api_url}/v1/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    content = ""
    if isinstance(data, dict) and data.get("choices"):
        message = data["choices"][0].get("message") or {}
        content = str(message.get("content") or "").strip()
    else:
        content = str(data)
    return {
        "provider": runtime.tag,
        "model": runtime.model_name,
        "content": content,
        "raw": data,
    }


async def execute_workflow(db: AsyncSession, workflow_id: int) -> dict[str, Any]:
    workflow_res = await db.execute(select(AIWorkflow).where(AIWorkflow.id == workflow_id))
    workflow = workflow_res.scalar_one_or_none()
    if workflow is None:
        raise RuntimeError("Workflow nicht gefunden.")

    tasks = await _load_workflow_tasks(db, workflow_id)
    tasks_by_key = _task_lookup(tasks)
    workflow.status = "running"
    workflow.updated_at = datetime.utcnow()
    await db.commit()

    executed: dict[str, dict[str, Any]] = {}
    pending_keys = [task.task_key for task in tasks]

    while pending_keys:
        ready_tasks = [tasks_by_key[key] for key in pending_keys if _task_ready(tasks_by_key[key], tasks_by_key)]
        if not ready_tasks:
            raise RuntimeError("Workflow enthält zirkuläre oder unerfüllte Abhängigkeiten.")

        parallel_tasks = [task for task in ready_tasks if task.execution_mode == "parallel"]
        sequential_tasks = [task for task in ready_tasks if task.execution_mode != "parallel"]

        async def _run(task: AIWorkflowTask) -> tuple[str, dict[str, Any]]:
            task.status = "running"
            task.started_at = datetime.utcnow()
            await db.commit()
            deps = [executed[dep]["content"] for dep in (task.depends_on or []) if dep in executed]
            try:
                result = await _call_provider(task, workflow, deps)
            except Exception as exc:
                task.status = "failed"
                task.error_text = str(exc)
                task.finished_at = datetime.utcnow()
                workflow.status = "failed"
                workflow.updated_at = datetime.utcnow()
                await db.commit()
                raise
            task.status = "done"
            task.result_text = result["content"]
            task.result_json = result
            task.result_files = []
            task.error_text = None
            task.finished_at = datetime.utcnow()
            await db.commit()
            return task.task_key, result

        if parallel_tasks:
            results = await asyncio.gather(*(_run(task) for task in parallel_tasks))
            for key, result in results:
                executed[key] = result
                pending_keys.remove(key)

        for task in sequential_tasks:
            key, result = await _run(task)
            executed[key] = result
            pending_keys.remove(key)

    workflow.status = "completed"
    workflow.updated_at = datetime.utcnow()
    await db.commit()
    return {
        "workflow_id": workflow.id,
        "status": workflow.status,
        "results": executed,
    }
