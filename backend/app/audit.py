import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AuditEvent
from .settings import get_settings


def write_audit(action: str, subject_type: str, subject_id: str, username: str, details: dict | None = None) -> AuditEvent:
    settings = get_settings()
    settings.audit_dir.mkdir(parents=True, exist_ok=True)
    event = AuditEvent(
        timestamp=datetime.now(timezone.utc),
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        username=username,
        details=details or {},
    )
    audit_file = settings.audit_dir / "audit.jsonl"
    with audit_file.open("a", encoding="utf-8") as handle:
        handle.write(event.model_dump_json())
        handle.write("\n")
    return event


def list_audit_events(*, subject_type: str | None = None, subject_id: str | None = None, username: str | None = None) -> list[AuditEvent]:
    settings = get_settings()
    audit_file = settings.audit_dir / "audit.jsonl"
    if not audit_file.exists():
        return []

    events: list[AuditEvent] = []
    for line in audit_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        event = AuditEvent.model_validate(payload)
        if subject_type and event.subject_type != subject_type:
            continue
        if subject_id and event.subject_id != subject_id:
            continue
        if username and event.username != username:
            continue
        events.append(event)

    events.sort(key=lambda event: event.timestamp, reverse=True)
    return events


def render_audit_event(event: AuditEvent) -> str:
    details = ", ".join(f"{key}={_render_value(value)}" for key, value in event.details.items())
    details = details or "keine Details"
    return f"{event.timestamp.isoformat()} | {event.username} | {event.action} | {event.subject_type}:{event.subject_id} | {details}"


def _render_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_render_value(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
