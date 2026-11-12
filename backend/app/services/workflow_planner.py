from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

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
