from __future__ import annotations

import re

from app.services.generated_files import build_generated_file_bytes_with_fallback

_GENERIC_PREFIXES = (
    'Der Bericht basiert direkt',
    'Der Bericht wurde',
    'Die Antwort basiert',
    'Für schwere Formate',
    'Wenn zusätzliche Dateitypen',
    'Kontext der lokalen Projektordner',
    'Lokale Projektordner',
    'Lokaler Ordner',
    'Der Desktop-Agent ist aktiv',
    'Nutze diesen Kontext',
    'Hinweis:',
)

_FACT_PREFIXES = (
    'Geodatenpaket für',
    'Geometrietyp:',
    'Bounding Box:',
    'Geometrien:',
    'Geometrie-Beispiele:',
    'Felder:',
    'Kontakte / Datensätze:',
    'Artenhinweise:',
    'Schwerpunkt der Kontakte:',
    'Beispielinhalt:',
    'Projektion:',
    'DBF vorhanden:',
    'Im pCloud-Projektordner',
    'Im lokalen Projektordner',
    'Im ausgewählten Ordnersatz',
    'Ordnerbaum des lokalen Projektordners',
)


def _normalize_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in (text or '').splitlines():
        line = raw.rstrip()
        if line:
            lines.append(line)
    return lines


def _strip_bullet_prefix(line: str) -> str:
    return re.sub(r'^[\s•\-–]+', '', (line or '')).strip()


def _is_noise_line(line: str) -> bool:
    stripped = _strip_bullet_prefix(line)
    return any(stripped.startswith(prefix) for prefix in _GENERIC_PREFIXES)


def _is_fact_line(line: str) -> bool:
    stripped = _strip_bullet_prefix(line)
    return any(stripped.startswith(prefix) for prefix in _FACT_PREFIXES)


def _extract_significant_lines(context_text: str, max_items: int = 18) -> list[str]:
    lines = _normalize_lines(context_text)
    facts: list[str] = []
    for line in lines:
        stripped = _strip_bullet_prefix(line)
        if not stripped or _is_noise_line(stripped):
            continue
        if _is_fact_line(stripped):
            facts.append(stripped)
            continue
        if stripped.startswith(('- ', '[Ordner]', '[Ordnerquelle]')):
            facts.append(stripped)
            continue
        if re.search(r'\.(shp|shx|dbf|prj|cpg|gpkg|pdf|docx|xlsx|csv|md|txt)\b', stripped, re.IGNORECASE):
            facts.append(stripped)
            continue
    if not facts:
        for line in lines:
            stripped = _strip_bullet_prefix(line)
            if not stripped or _is_noise_line(stripped):
                continue
            facts.append(stripped)
            if len(facts) >= max_items:
                break
    deduped: list[str] = []
    seen: set[str] = set()
    for item in facts:
        normalized = re.sub(r'\s+', ' ', item).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def _extract_file_names(context_text: str, max_items: int = 20) -> list[str]:
    names: list[str] = []
    for line in _normalize_lines(context_text):
        stripped = _strip_bullet_prefix(line)
        if not stripped:
            continue
        match = re.match(r'^-\s+(.+?)(?:\s+\(|$)', stripped)
        if match:
            candidate = match.group(1).strip()
            if candidate and candidate not in names:
                names.append(candidate)
        match = re.search(r'Datei:\s*(.+)$', stripped)
        if match:
            candidate = match.group(1).strip()
            if candidate and candidate not in names:
                names.append(candidate)
        if len(names) >= max_items:
            break
    return names


def build_project_report_fallback(question: str, project_files_context: str, project_name: str | None = None) -> str:
    title = (project_name or 'Projektbericht').strip() or 'Projektbericht'
    question_text = (question or '').strip() or 'Analyse der Projektdateien'
    report_text = (project_files_context or '').strip()

    if report_text:
        report_lines = _normalize_lines(report_text)
        looks_like_report = (
            len(report_lines) >= 4
            and (
                report_text.lstrip().startswith('#')
                or '## ' in report_text
                or any(
                    marker in report_text.lower()
                    for marker in ('zusammenfassung', 'analyse', 'schluss', 'ergebnis', 'befund', 'fassung', 'bewertung')
                )
            )
        )
        if looks_like_report:
            return '\n'.join([
                f'# {title}',
                '',
                report_text,
            ])

    facts = _extract_significant_lines(report_text)
    file_names = _extract_file_names(report_text)

    report: list[str] = [
        f'# {title}',
        '',
        '## Zusammenfassung',
        f'Bericht zur Anfrage: {question_text}',
    ]

    if facts:
        report.append('Die folgenden Fakten wurden direkt aus den extrahierten Projektinhalten übernommen:')
        report.extend([f'- {fact}' for fact in facts[:8]])
    else:
        report.append('Es konnten keine detaillierten Inhaltsfakten aus dem Kontext extrahiert werden; nur die Dateistruktur war verfügbar.')

    if file_names:
        report.extend(['', '## Gefundene Dateien'])
        report.extend([f'- {name}' for name in file_names[:20]])

    report.extend(['', '## Analyse'])
    if facts:
        report.append('Der Bericht stützt sich auf den tatsächlichen Dateiinhalt und die technische Struktur des Projektordners.')
        if any('Geodatenpaket' in fact or 'Geometrietyp' in fact for fact in facts):
            report.append('Es handelt sich um einen Geodatensatz bzw. GIS-nahen Projektordner; relevante Inhalte sind Geometrietyp, Bounding Box, Felder und Datensatzanzahl.')
        if any('Beispielinhalt' in fact for fact in facts):
            report.append('Die Attributdaten wurden aus der Datenquelle selbst ausgelesen, nicht aus Dateinamen geraten.')
    else:
        report.append('Es lagen nur Dateinamen und Strukturinformationen vor. Für eine belastbare inhaltliche Analyse muss der Ordnerkontext mit echten Datei-Inhalten erneut gelesen werden.')

    report.extend(['', '## Schluss'])
    if facts:
        report.append('Die Antwort basiert auf den aus den Dateien extrahierten Fakten und nicht auf einer generischen Vorlage.')
    else:
        report.append('Die Antwort basiert auf dem verfügbaren Ordnerkontext; für einen präziseren Bericht sind lesbare Dateiinhalte erforderlich.')
    return '\n'.join(report)


def build_project_report_generated_file(
    question: str,
    project_files_context: str,
    project_name: str | None = None,
    filename_hint: str = 'project_report',
) -> tuple[bytes, str, str]:
    report_body = build_project_report_fallback(question, project_files_context, project_name=project_name)
    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', (project_name or filename_hint).strip()).strip('_') or filename_hint
    return build_generated_file_bytes_with_fallback(f'{safe_name}.docx', report_body)
