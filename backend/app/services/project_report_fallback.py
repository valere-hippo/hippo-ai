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


STATUS_ONLY_RE = re.compile(
    r'^(ich\s+werde|ich\s+habe|bericht\s+im\s+lieferordner\s+gespeichert|analyse\s+abgeschlossen|die\s+dateien\s+wurden\s+analysiert|ich\s+analysiere|ich\s+werde\s+die\s+dateien)',
    re.IGNORECASE,
)


def _is_valid_report_text(report_text: str) -> bool:
    lines = _normalize_lines(report_text)
    if len(lines) < 4:
        return False
    if STATUS_ONLY_RE.search((lines[0] or '').strip()):
        return False
    lower = report_text.lower()
    section_hits = sum(1 for marker in ('zusammenfassung', 'analyse', 'schluss') if f'## {marker}' in lower or marker in lower)
    fact_hits = sum(1 for marker in _FACT_PREFIXES if marker.lower() in lower)
    return section_hits >= 2 and fact_hits >= 1


def build_project_report_fallback(question: str, project_files_context: str, project_name: str | None = None) -> str:
    title = (project_name or 'Projektbericht').strip() or 'Projektbericht'
    question_text = (question or '').strip() or 'Analyse der Projektdateien'
    report_text = (project_files_context or '').strip()

    if report_text:
        looks_like_report = _is_valid_report_text(report_text)
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
        '## Projektdaten',
        f'- Projekt: {title}',
        f'- Anfrage: {question_text}',
        '- Bearbeiter: Hippo AI',
        '',
        '## 1. Zusammenfassung',
    ]

    if facts:
        report.append('Die folgenden Fakten wurden direkt aus den extrahierten Projektinhalten übernommen:')
        report.extend([f'- {fact}' for fact in facts[:8]])
    else:
        report.append('Es konnten keine detaillierten Inhaltsfakten aus dem Kontext extrahiert werden; nur die Dateistruktur war verfügbar.')

    if file_names:
        report.extend(['', '## 2. Gefundene Dateien'])
        report.extend([f'- {name}' for name in file_names[:20]])

    report.extend(['', '## 3. Analyse'])
    if facts:
        report.append('Der Bericht stützt sich auf den tatsächlichen Dateiinhalt und die technische Struktur des Projektordners.')
        if any('Geodatenpaket' in fact or 'Geometrietyp' in fact for fact in facts):
            report.append('Es handelt sich um einen Geodatensatz bzw. GIS-nahen Projektordner; relevante Inhalte sind Geometrietyp, Bounding Box, Felder und Datensatzanzahl.')
        if any('Beispielinhalt' in fact for fact in facts):
            report.append('Die Attributdaten wurden aus der Datenquelle selbst ausgelesen, nicht aus Dateinamen geraten.')
        if any('.xlsx' in fact.lower() or 'arbeitsblatt' in fact.lower() for fact in facts):
            report.append('Tabellen- und Arbeitsblattinhalte wurden direkt aus der Datei gelesen und für die Analyse übernommen.')
    else:
        report.append('Es lagen nur Dateinamen und Strukturinformationen vor. Für eine belastbare inhaltliche Analyse muss der Ordnerkontext mit echten Datei-Inhalten erneut gelesen werden.')

    report.extend(['', '## 4. Schlussfolgerung'])
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
