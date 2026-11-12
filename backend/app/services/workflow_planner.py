from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

from app.services.generated_files import build_generated_file_bytes_with_fallback

MODEL_TAG_ALIASES = {
    "openai": "openai",
    "gpt": "openai",
    "claude": "claude",
    "anthropic": "claude",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "qween": "qwen",
    "alibaba": "qwen",
    "tencent": "tencent",
    "hunyuan": "tencent",
}

FINAL_TASK_KEYWORDS = (
    "bericht",
    "report",
    "synthese",
    "synthesis",
    "zusammenfassung",
    "final",
    "endbericht",
)

INPUT_KIND_HINTS = [
    ("geodata", "geodata"),
    ("gis", "geodata"),
    ("qgis", "geodata"),
    ("shp", "geodata"),
    ("shx", "geodata"),
    ("dbf", "geodata"),
    ("prj", "geodata"),
    ("cpg", "geodata"),
    ("image", "images"),
    ("bild", "images"),
    ("photo", "images"),
    ("foto", "images"),
    ("ocr", "images"),
    ("text", "text"),
    ("pdf", "text"),
    ("doc", "text"),
    ("docx", "text"),
    ("xlsx", "text"),
    ("csv", "text"),
]

MODEL_TAG_RE = re.compile(r"#([A-Za-z0-9:_-]+)")
AFTER_RE = re.compile(r"#(?:after|depends(?:_on)?):([A-Za-z0-9_-]+)", re.IGNORECASE)
PARALLEL_RE = re.compile(r"#parallel\b", re.IGNORECASE)
FINAL_RE = re.compile(r"#final\b", re.IGNORECASE)
WORKFLOW_TAG_RE = re.compile(r"#(?:[A-Za-z0-9:_-]+)")


def has_workflow_markers(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    if not WORKFLOW_TAG_RE.search(text):
        return False
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            '#openai',
            '#claude',
            '#deepseek',
            '#qwen',
            '#qween',
            '#tencent',
            '#parallel',
            '#after:',
            '#depends',
            '#final',
        )
    )


@dataclass(slots=True)
class PlannedTask:
    task_key: str
    title: str
    instruction: str
    model_tag: str
    input_kind: str
    execution_mode: str
    depends_on: list[str]
    sort_order: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_model_tag(raw: str | None, default: str = "openai") -> str:
    candidate = (raw or "").strip().lower().lstrip("#")
    if not candidate:
        return default
    return MODEL_TAG_ALIASES.get(candidate, candidate)


def infer_input_kind(text: str) -> str:
    lowered = (text or "").lower()
    for needle, kind in INPUT_KIND_HINTS:
        if needle in lowered:
            return kind
    return "mixed"


def infer_title(text: str, index: int) -> str:
    cleaned = re.sub(r"\s+", " ", re.sub(r"#\S+", "", text or "")).strip(" -–—:\t")
    if not cleaned:
        return f"Tâche {index + 1}"
    words = cleaned.split()
    if len(words) > 10:
        cleaned = " ".join(words[:10])
    return cleaned[:200]


def is_final_task(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in FINAL_TASK_KEYWORDS) or bool(FINAL_RE.search(lowered))


def parse_workflow_message(message: str) -> list[PlannedTask]:
    lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
    if not lines:
        return []

    tasks: list[PlannedTask] = []
    for idx, line in enumerate(lines, start=1):
        raw_tags = MODEL_TAG_RE.findall(line)
        normalized_tags = [normalize_model_tag(tag, "") for tag in raw_tags]
        model_tag = next((tag for tag in normalized_tags if tag), "openai")
        if not model_tag:
            model_tag = "openai"

        depends_on = AFTER_RE.findall(line)
        cleaned_instruction = MODEL_TAG_RE.sub("", line)
        cleaned_instruction = AFTER_RE.sub("", cleaned_instruction)
        cleaned_instruction = PARALLEL_RE.sub("", cleaned_instruction)
        cleaned_instruction = FINAL_RE.sub("", cleaned_instruction)
        cleaned_instruction = re.sub(r"\s+", " ", cleaned_instruction).strip(" -–—:\t")
        if not cleaned_instruction:
            cleaned_instruction = line.strip()

        execution_mode = "parallel" if PARALLEL_RE.search(line) or not depends_on else "sequential"
        input_kind = infer_input_kind(cleaned_instruction)
        task_key = f"t{idx}"
        title = infer_title(cleaned_instruction, idx - 1)

        tasks.append(
            PlannedTask(
                task_key=task_key,
                title=title,
                instruction=cleaned_instruction,
                model_tag=model_tag,
                input_kind=input_kind,
                execution_mode=execution_mode,
                depends_on=list(dict.fromkeys(depends_on)),
                sort_order=idx - 1,
            )
        )

    prior_keys: list[str] = []
    for task in tasks:
        if is_final_task(task.instruction) and not task.depends_on:
            task.depends_on = prior_keys.copy()
            task.execution_mode = "sequential" if task.depends_on else task.execution_mode
        prior_keys.append(task.task_key)

    return tasks


def build_workflow_metadata(message: str, *, final_model_tag: str | None = None, default_model_tag: str = "openai") -> dict[str, Any]:
    tasks = parse_workflow_message(message)
    workflow_status = "pending" if tasks else "empty"
    return {
        "status": workflow_status,
        "final_model_tag": normalize_model_tag(final_model_tag, default_model_tag) if final_model_tag else (normalize_model_tag(default_model_tag, "openai") if tasks else None),
        "tasks": [task.to_dict() for task in tasks],
    }


def build_workflow_execution_summary(plan: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    tasks = plan.get("tasks") or []
    results = execution.get("results") or {}
    task_summaries: list[dict[str, Any]] = []
    final_result: dict[str, Any] | None = None

    for task in tasks:
        task_key = task.get("task_key")
        result = results.get(task_key, {}) if isinstance(results, dict) else {}
        content = str(result.get("content") or "").strip()
        provider = str(result.get("provider") or task.get("model_tag") or "openai")
        model = str(result.get("model") or "")
        status = str(result.get("status") or ("done" if content else "empty"))
        summary = {
            "task_key": task_key,
            "title": task.get("title"),
            "model_tag": task.get("model_tag"),
            "provider": provider,
            "model": model,
            "status": status,
            "depends_on": task.get("depends_on") or [],
            "is_final": task.get("model_tag") == plan.get("final_model_tag"),
            "content": content,
        }
        task_summaries.append(summary)
        if summary["is_final"] and content:
            final_result = summary

    if final_result is None:
        for summary in reversed(task_summaries):
            if summary["content"]:
                final_result = summary
                break

    return {
        "workflow_id": execution.get("workflow_id"),
        "status": execution.get("status") or "unknown",
        "task_count": len(task_summaries),
        "tasks": task_summaries,
        "final_result": final_result or {},
    }


def summarize_workflow_execution(plan: dict[str, Any], execution: dict[str, Any]) -> str:
    summary = build_workflow_execution_summary(plan, execution)
    tasks = summary.get("tasks") or []
    lines: list[str] = []
    lines.append(f"Workflow-ID: {summary.get('workflow_id')}")
    lines.append(f"Status: {summary.get('status') or 'unknown'}")
    lines.append("")
    lines.append("Teilaufgaben")
    for task in tasks:
        content = str(task.get("content") or "").strip()
        model_tag = task.get("model_tag") or task.get("provider") or "openai"
        status = "done" if content else "empty"
        lines.append(f"- {task.get('task_key')} · {model_tag} · {status} · {task.get('title')}")
        if content:
            preview = content if len(content) <= 1200 else content[:1200].rstrip() + "…"
            lines.append(f"  {preview}")
    final_result = summary.get("final_result") or {}
    final_content = str(final_result.get("content") or "").strip()
    if final_content:
        lines.append("")
        lines.append("Endbericht")
        lines.append(final_content)
    return "\n".join(lines).strip()


def build_workflow_task_generated_file(task: dict[str, Any], *, workflow_id: int | None = None, filename_hint: str | None = None) -> tuple[bytes, str, str]:
    task_key = str(task.get('task_key') or 'task').strip() or 'task'
    provider = str(task.get('provider') or task.get('model_tag') or 'openai').strip().lower() or 'openai'
    prefix = filename_hint or f"workflow_{workflow_id or 'x'}_{task_key}_{provider}"
    filename = f"{prefix}.docx"
    content = str(task.get('content') or '').strip()
    if not content:
        content = str(task.get('title') or task_key).strip() or 'Workflow-Task'
    lines = [
        f"Task: {task.get('title') or task_key}",
        f"Workflow-ID: {workflow_id if workflow_id is not None else 'unbekannt'}",
        f"Task-Key: {task_key}",
        f"Provider: {provider}",
        f"Status: {task.get('status') or 'done'}",
    ]
    depends_on = task.get('depends_on') or []
    if depends_on:
        lines.append(f"Abhängigkeiten: {', '.join(str(dep) for dep in depends_on)}")
    lines.append('')
    lines.append(content)
    body = '\n'.join(lines)
    return build_generated_file_bytes_with_fallback(filename, body)


def build_workflow_task_generated_files(summary: dict[str, Any], *, filename_hint: str | None = None) -> list[tuple[bytes, str, str]]:
    workflow_id = summary.get('workflow_id')
    files: list[tuple[bytes, str, str]] = []
    for task in summary.get('tasks') or []:
        if not str(task.get('content') or '').strip():
            continue
        files.append(build_workflow_task_generated_file(task, workflow_id=workflow_id, filename_hint=filename_hint))
    return files


def build_workflow_summary_generated_file(plan: dict[str, Any], execution: dict[str, Any], *, filename_hint: str = "workflow_report") -> tuple[bytes, str, str]:
    summary_text = summarize_workflow_execution(plan, execution)
    filename = f"{filename_hint}.docx"
    return build_generated_file_bytes_with_fallback(filename, summary_text)
