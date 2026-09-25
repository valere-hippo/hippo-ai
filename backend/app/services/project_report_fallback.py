from __future__ import annotations

import re


def _normalize_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line:
            lines.append(line)
    return lines


def _strip_bullet_prefix(line: str) -> str:
    return re.sub(r"^[\s•\-–]+", "", (line or "")).strip()


def _is_file_marker(line: str) -> bool:
    stripped = _strip_bullet_prefix(line)
    return stripped.lower().startswith(("datei:", "dateien:", "dateiliste:", "enthaltende dateien:", "enthält"))


def _summarize_context_lines(context_text: str, max_items: int = 14) -> list[str]:
    lines = _normalize_lines(context_text)
    bullets: list[str] = []
    for line in lines:
        if _is_file_marker(line):
            continue
        stripped = _strip_bullet_prefix(line)
        if not stripped:
            continue
        if len(stripped) > 260:
            stripped = stripped[:257].rstrip() + "…"
        bullets.append(stripped)
        if len(bullets) >= max_items:
            break
    return bullets


def build_project_report_fallback(question: str, project_files_context: str, project_name: str | None = None) -> str:
    title = (project_name or "Projektbericht").strip() or "Projektbericht"
    question_text = (question or "").strip() or "Analyse der Projektdateien"
    context_text = (project_files_context or "").strip()
    context_lines = _normalize_lines(context_text)
    context_bullets = _summarize_context_lines(context_text)

    summary_note = (
        "Die Modellantwort ist nicht rechtzeitig zurückgekommen, daher wurde dieser Bericht aus dem tatsächlich ermittelten Projektkontext erzeugt. "
        "Die folgenden Abschnitte beruhen auf den extrahierten Datei- und Formatinformationen, nicht auf erfundenen Platzhaltern."
    )

    report: list[str] = [
        f"# {title}",
        "",
        "## Anfrage",
        question_text,
        "",
        "## Kurzbewertung",
        summary_note,
        "",
    ]

    if context_lines:
        report.extend([
            "## Extrahierter Projektkontext",
        ])
        for bullet in context_bullets:
            report.append(f"- {bullet}")
        report.append("")

    report.extend([
        "## Technische Einordnung",
        "- Der Bericht wurde auf Basis der Datei- und Inhaltsextraktion des Projektordners erstellt.",
        "- Für Textdateien, Office-Dateien, Tabellen, Bilder, Geo-Daten und Medien werden unterschiedliche Extraktoren benutzt.",
        "- Wenn zusätzliche Dateitypen auftauchen, werden passende Tools automatisch erzeugt und beim nächsten Sync berücksichtigt.",
        "",
        "## Ausführliche Beobachtungen",
    ])

    if context_lines:
        for line in context_lines[:60]:
            if _is_file_marker(line):
                continue
            report.append(f"- {_strip_bullet_prefix(line)}")
    else:
        report.append("- Kein detaillierter Projektkontext verfügbar.")

    report.extend([
        "",
        "## Fazit",
        "- Die Antwort basiert auf dem aktuellen Projektkontext und den aus den Dateien extrahierten Inhalten.",
        "- Für schwere Formate wie PDF, GIS, Audio und Video wird der Report mit spezialisierten Extraktoren angereichert.",
        "- Wenn du möchtest, kann ich daraus als nächsten Schritt eine noch stärker gegliederte Word-Fassung mit separaten Kapiteln pro Dateityp erzeugen.",
    ])
    return "\n".join(report)
