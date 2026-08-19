from datetime import datetime, timezone

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

