from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncio
import json
import logging
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.project import Project
from app.models.workflow import AIWorkflow, AIWorkflowTask
from app.services.project_storage import build_project_files_context
from app.services.provider_clients import (
    build_chat_completion_payload,
    build_fallback_model_choices,
    build_provider_headers,
    describe_provider_http_error,
    resolve_provider_runtime,
)
from app.services.workflow_planner import build_workflow_execution_summary

logger = logging.getLogger("hippo-ai.workflow")


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


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        candidate = item.strip().lower()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def _task_source_prefixes(task: AIWorkflowTask) -> list[str]:
    text = f"{getattr(task, 'title', '')} {getattr(task, 'instruction', '')} {getattr(task, 'input_kind', '')}".lower()
    prefixes: list[str] = []

    if getattr(task, "input_kind", "") == "images" or any(token in text for token in ("bild", "image", "photo", "foto", "scan", "ortho", "orthofoto")):
        prefixes.extend(["image", "images", "bild", "bilder", "photo", "photos", "foto", "fotos"])
    if getattr(task, "input_kind", "") == "geodata" or any(token in text for token in ("geo", "gis", "qgis", "shape", "shp", "gpkg", "wms", "wfs", "kart", "koord", "geod")):
        prefixes.extend(["geo", "geodata", "gis", "qgis", "shape", "shp", "gpkg", "kart", "karten", "koordin", "coords"])
    if getattr(task, "input_kind", "") == "text" or any(token in text for token in ("text", "bericht", "doc", "docx", "pdf", "csv", "xlsx", "txt", "rtf")):
        prefixes.extend(["text", "texte", "docs", "doc", "docx", "pdf", "csv", "xlsx", "bericht", "report", "txt"])

    if not prefixes and getattr(task, "input_kind", "") not in {"mixed", ""}:
        prefixes.append(str(getattr(task, "input_kind", "")).strip().lower())
    return _dedupe_preserve_order(prefixes)


def _context_is_uninformative(context: str) -> bool:
    lowered = (context or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "keine dateien zuverlässig ausgelesen",
            "keine dateien sichtbar",
            "noch keine dateien",
            "leerer ordner",
            "kontext fehlt",
            "nicht lesbar",
        )
    )


async def build_task_file_context(db: AsyncSession, workflow: AIWorkflow, task: AIWorkflowTask) -> str:
    if workflow.project_id is None:
        return ""
    project_res = await db.execute(select(Project).where(Project.id == workflow.project_id))
    project = project_res.scalar_one_or_none()
    if project is None:
        return ""
    source_prefixes = _task_source_prefixes(task)
    context = await build_project_files_context(
        project,
        question=task.instruction,
        source_prefixes=source_prefixes or None,
    )
    if source_prefixes and _context_is_uninformative(context):
        fallback_context = await build_project_files_context(
            project,
            question=task.instruction,
            source_prefixes=None,
        )
        if fallback_context.strip():
            return fallback_context
    return context


def _build_task_messages(
    workflow: AIWorkflow,
    task: AIWorkflowTask,
    dependency_texts: list[str],
    file_context: str = "",
) -> list[dict[str, str]]:
    context_bits = [
        f"Workflow-ID: {workflow.id}",
        f"Task-Key: {task.task_key}",
        f"Task-Titel: {task.title}",
        f"Input-Kind: {task.input_kind}",
        f"Execution-Mode: {task.execution_mode}",
        f"Aufgabe: {task.instruction}",
    ]
    if file_context.strip():
        context_bits.append(
            "Reale lokale Projektdaten aus dem Dateisystem (dieser Kontext stammt aus echten Dateien und hat Vorrang vor allgemeinen Annahmen):\n"
            f"{file_context.strip()}"
        )
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


async def _call_provider(task: AIWorkflowTask, workflow: AIWorkflow, dependency_texts: list[str], file_context: str = "") -> dict[str, Any]:
    runtime = resolve_provider_runtime(task.model_tag)
    if not runtime.api_url:
        raise RuntimeError(json.dumps({
            "provider": runtime.tag,
            "model": runtime.model_name,
            "api_url": runtime.api_url,
            "error_kind": "missing_configuration",
            "error_message": f"Kein API-URL für Provider {runtime.tag} konfiguriert.",
        }, ensure_ascii=False))
    headers = build_provider_headers(runtime.api_key)
    messages = _build_task_messages(workflow, task, dependency_texts, file_context=file_context)
    payload = build_chat_completion_payload(runtime.model_name, messages, max_tokens=4096, temperature=0.25)
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
        try:
            response = await client.post(f"{runtime.api_url}/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            error_info = describe_provider_http_error(exc, provider=runtime.tag, model_name=runtime.model_name, api_url=runtime.api_url)
            raise RuntimeError(json.dumps(error_info, ensure_ascii=False)) from exc
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


async def queue_workflow_execution(db: AsyncSession, workflow_id: int) -> None:
    workflow_res = await db.execute(select(AIWorkflow).where(AIWorkflow.id == workflow_id))
    workflow = workflow_res.scalar_one_or_none()
    if workflow is None:
        raise RuntimeError("Workflow nicht gefunden.")
    workflow.status = "queued"
    workflow.updated_at = datetime.utcnow()
    await db.commit()


async def claim_next_queued_workflow(db: AsyncSession) -> int | None:
    result = await db.execute(
        select(AIWorkflow)
        .where(AIWorkflow.status == "queued")
        .order_by(AIWorkflow.updated_at.asc(), AIWorkflow.created_at.asc(), AIWorkflow.id.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        return None
    workflow.status = "running"
    workflow.updated_at = datetime.utcnow()
    await db.commit()
    return workflow.id


async def execute_workflow_by_id(workflow_id: int) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await execute_workflow(db, workflow_id)


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
    failed_task: dict[str, Any] | None = None
    workflow_state = "completed"

    while pending_keys:
        ready_tasks = [tasks_by_key[key] for key in pending_keys if _task_ready(tasks_by_key[key], tasks_by_key)]
        if not ready_tasks:
            workflow_state = "failed"
            break

        parallel_tasks = [task for task in ready_tasks if task.execution_mode == "parallel"]
        sequential_tasks = [task for task in ready_tasks if task.execution_mode != "parallel"]

        async def _run(task: AIWorkflowTask) -> tuple[str, dict[str, Any]]:
            task.status = "running"
            task.started_at = datetime.utcnow()
            await db.commit()
            deps = [executed[dep]["content"] for dep in (task.depends_on or []) if dep in executed]
            file_context = await build_task_file_context(db, workflow, task)
            try:
                result = await _call_provider(task, workflow, deps, file_context=file_context)
            except Exception as exc:
                error_info: dict[str, Any]
                try:
                    error_info = json.loads(str(exc)) if str(exc).strip().startswith("{") else {"error_message": str(exc)}
                except Exception:
                    error_info = {"error_message": str(exc)}
                result = {
                    "provider": getattr(task, 'model_tag', None) or "openai",
                    "model": resolve_provider_runtime(task.model_tag).model_name,
                    "content": "",
                    "status": "failed",
                    **error_info,
                }
                task.status = "failed"
                task.error_text = json.dumps(error_info, ensure_ascii=False)
                task.result_json = result
                task.result_text = None
                task.result_files = []
                task.finished_at = datetime.utcnow()
                workflow.status = "failed"
                workflow.updated_at = datetime.utcnow()
                await db.commit()
                logger.warning(
                    "Workflow task failed | workflow=%s | task=%s | provider=%s | model=%s | kind=%s | message=%s",
                    workflow.id,
                    task.task_key,
                    error_info.get('provider'),
                    error_info.get('model'),
                    error_info.get('error_kind'),
                    error_info.get('error_message'),
                )
                return task.task_key, result
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
                if result.get("status") == "failed" and failed_task is None:
                    failed_task = {"task_key": key, **result}
                    workflow_state = "needs_model_choice" if result.get("error_kind") in {"unauthorized", "forbidden", "not_found", "unprocessable_entity", "service_unavailable", "timeout", "connection_error"} else "failed"
                    pending_keys.clear()
                    break
            if workflow_state != "completed":
                break

        for task in sequential_tasks:
            key, result = await _run(task)
            executed[key] = result
            pending_keys.remove(key)
            if result.get("status") == "failed":
                failed_task = {"task_key": key, **result}
                workflow_state = "needs_model_choice" if result.get("error_kind") in {"unauthorized", "forbidden", "not_found", "unprocessable_entity", "service_unavailable", "timeout", "connection_error"} else "failed"
                pending_keys.clear()
                break
        if workflow_state != "completed":
            break

    workflow.status = workflow_state
    workflow.updated_at = datetime.utcnow()
    await db.commit()
    summary = build_workflow_execution_summary(
        {"workflow_id": workflow.id, "final_model_tag": workflow.final_model_tag, "tasks": [task.__dict__ for task in tasks]},
        {"workflow_id": workflow.id, "status": workflow.status, "results": executed},
    )
    resolution = None
    if failed_task:
        resolution = {
            "task_key": failed_task.get("task_key"),
            "title": failed_task.get("title"),
            "instruction": failed_task.get("instruction"),
            "provider": failed_task.get("provider"),
            "model": failed_task.get("model"),
            "error_kind": failed_task.get("error_kind"),
            "error_message": failed_task.get("error_message"),
            "choices": build_fallback_model_choices(exclude_provider=str(failed_task.get("provider") or "")),
        }
    return {
        "workflow_id": workflow.id,
        "status": workflow.status,
        "results": executed,
        "summary": summary,
        "resolution": resolution,
    }
