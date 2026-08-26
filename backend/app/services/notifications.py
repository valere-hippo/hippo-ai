from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Iterable

from app.core.config import settings
from app.services.project_storage import has_s3_storage, project_bucket_name


def smtp_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_sender)


def _send_email_sync(subject: str, body: str, recipients: Iterable[str]) -> bool:
    recipient_list = [recipient.strip() for recipient in recipients if recipient and recipient.strip()]
    if not smtp_is_configured() or not recipient_list:
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_sender
    message["To"] = ", ".join(recipient_list)
    message.set_content(body)

    if settings.smtp_use_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)

    try:
        if settings.smtp_use_tls and not settings.smtp_use_ssl:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password or "")
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            pass

    return True


async def send_email(subject: str, body: str, recipients: Iterable[str]) -> bool:
    return await asyncio.to_thread(_send_email_sync, subject, body, recipients)


async def notify_user_created(user, creator=None) -> bool:
    if not smtp_is_configured():
        return False
    subject = "HIPPO-AI: Dein Konto wurde erstellt"
    lines = [
        f"Hallo {user.full_name},",
        "",
        "dein HIPPO-AI-Konto wurde erstellt.",
        f"E-Mail: {user.email}",
        f"Rolle: {getattr(user, 'role', 'USER')}",
    ]
    if creator is not None:
        lines.append(f"Erstellt von: {getattr(creator, 'full_name', creator.email)}")
    lines.extend(
        [
            "",
            "Du kannst dich jetzt mit dieser E-Mail-Adresse anmelden.",
            "Wenn du ein Passwort-Reset benötigst, kontaktiere bitte dein Team.",
        ]
    )
    return await send_email(subject, "\n".join(lines), [user.email])


async def notify_project_created(project, owner) -> bool:
    if not smtp_is_configured():
        return False
    bucket_text = project_bucket_name(project) if has_s3_storage() else "Lokaler Speicher"
    subject = f'HIPPO-AI: Projekt "{project.name}" wurde erstellt'
    body = "\n".join(
        [
            f"Hallo {owner.full_name},",
            "",
            f'dein Projekt "{project.name}" wurde erstellt.',
            f"Projekt-ID: {project.id}",
            f"Speicher: {bucket_text}",
            "",
            "Du kannst Dateien direkt in der App hochladen und wieder herunterladen.",
        ]
    )
    return await send_email(subject, body, [owner.email])
