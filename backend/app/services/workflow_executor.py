from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncio
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.workflow import AIWorkflow, AIWorkflowTask
from app.services.project_storage import build_project_files_context
from app.services.provider_clients import build_chat_completion_payload, build_provider_headers, resolve_provider_runtime
from app.services.workflow_planner import build_workflow_execution_summary


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
        raise RuntimeError(f"Kein API-URL für Provider {runtime.tag} konfiguriert.")
    headers = build_provider_headers(runtime.api_key)
    messages = _build_task_messages(workflow, task, dependency_texts, file_context=file_context)
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
            file_context = await build_task_file_context(db, workflow, task)
            try:
                result = await _call_provider(task, workflow, deps, file_context=file_context)
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
    summary = build_workflow_execution_summary(
        {"workflow_id": workflow.id, "final_model_tag": workflow.final_model_tag, "tasks": [task.__dict__ for task in tasks]},
        {"workflow_id": workflow.id, "status": workflow.status, "results": executed},
    )
    return {
        "workflow_id": workflow.id,
        "status": workflow.status,
        "results": executed,
        "summary": summary,
    }
