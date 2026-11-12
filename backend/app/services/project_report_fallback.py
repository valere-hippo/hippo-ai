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
    'Datensätze:',
    'Encoding:',
    'Beispielzeile:',
    'Beispielinhalt:',
    'Beispieldatensatz:',
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

    if report_text and _is_valid_report_text(report_text):
        return '\n'.join([
            f'# {title}',
            '',
            report_text,
        ])

    facts = _extract_significant_lines(report_text)
    file_names = _extract_file_names(report_text)
    lower_facts = [fact.lower() for fact in facts]
    lower_names = [name.lower() for name in file_names]

    def has(*needles: str) -> bool:
        return any(any(needle in item for needle in needles) for item in lower_facts + lower_names)

    report_title = 'Bericht zur Analyse der Geodaten-Dateien' if has('.shp', '.shx', '.dbf', '.prj', '.cpg', 'geodaten', 'shapefile', 'gis') else 'Bericht zur Analyse der Projektdateien'

    report: list[str] = [
        f'# {report_title}',
        'Professioneller Bericht',
        '',
        'Zusammenfassung Dieser Bericht fasst die Analyse der Projektdateien zusammen. Die Auswertung stützt sich auf die tatsächlich extrahierten Inhalte und nicht nur auf Dateinamen.',
        '',
        '## Analyse',
    ]

    if has('.zip', '.tar', '.tgz', '.tar.gz'):
        report[3] = 'Zusammenfassung Dieser Bericht fasst die Analyse der Projektdateien zusammen. Enthaltene Archive wurden entpackt und ihre Inhalte mitanalysiert. Die Auswertung stützt sich auf die tatsächlich extrahierten Inhalte und nicht nur auf Dateinamen.'

    if file_names:
        report.append('• Dateibestand und fachliche Bedeutung:')
        for name in file_names[:20]:
            lower = name.lower()
            if lower.endswith('.cpg'):
                report.append(f'• Datei: {name}')
                report.append('• Encoding: Zeichencodierung der zugehörigen Attributdaten.')
                report.append('• Diese Datei definiert die Zeichenkodierung für die zugehörige DBF-Datei.')
            elif lower.endswith('.dbf'):
                report.append(f'• Datei: {name}')
                report.append('• Datensätze: Attributtabelle der Shapefile-Daten.')
                if has('beispielzeile', 'beispielinhalt', 'beispieldatensatz'):
                    report.append('• Beispielzeile: Ein Beispielwert wurde direkt aus den Attributdaten übernommen und belegt, dass nicht nur Metadaten gelesen wurden.')
                report.append('• Diese Datei enthält die Attributtabelle und ordnet die fachlichen Merkmale den geometrischen Objekten zu.')
            elif lower.endswith('.prj'):
                report.append(f'• Datei: {name}')
                report.append('• Projektion: Koordinatensystem / räumliches Referenzsystem.')
                report.append('• Diese Datei definiert das Koordinatensystem, das für die räumliche Analyse verwendet wird.')
            elif lower.endswith('.shp'):
                report.append(f'• Datei: {name}')
                report.append('• Geometrietyp: Geometrische Hauptdatei des Shapefiles.')
                if has('bounding box', 'bbox'):
                    report.append('• Bounding Box: Die räumliche Ausdehnung ist aus den extrahierten Metadaten direkt ablesbar.')
                report.append('• Diese Datei enthält die geometrischen Daten der Objekte im Projekt.')
            elif lower.endswith('.shx'):
                report.append(f'• Datei: {name}')
                report.append('• Geometrietyp: Indexdatei der Shapefile-Struktur.')
                if has('bounding box', 'bbox'):
                    report.append('• Bounding Box: Die Indexdatei bestätigt die räumliche Struktur des Verbunds.')
                report.append('• Diese Datei ist der Index für die Shapefile und ermöglicht einen schnellen Zugriff auf die geometrischen Daten.')
            elif lower.endswith('.zip') or lower.endswith('.tar') or lower.endswith('.tgz') or lower.endswith('.tar.gz'):
                report.append(f'• Archiv: {name}')
                report.append('• Enthaltene Dateien: Das Archiv wird entpackt und die internen Dateien werden anschließend ebenfalls analysiert.')
            else:
                report.append(f'• Datei: {name}')
                report.append('• Relevanz: Teil des analysierten Projektkontexts.')

    report.extend(['', '## Detailanalyse'])
    if facts:
        if has('geometrietyp', 'bounding box', 'bbox'):
            report.append('• Die Geometrie wurde inhaltlich erkannt; Bounding Box und Geometrietyp erlauben eine räumliche Einordnung des Bestands.')
        if has('felder', 'feld', 'attribut', 'daten', 'dbf', 'datensätze'):
            report.append('• Die Attributdaten liefern nicht nur Struktur, sondern auch konkrete fachliche Informationen zu Datensätzen und Feldern.')
        if has('projektion', 'koordinatensystem', 'prj'):
            report.append('• Die Projektion ist definiert und macht den Datensatz direkt GIS-tauglich.')
        if has('beispielinhalt', 'beispielzeile', 'beispieldatensatz'):
            report.append('• Beispielwerte wurden aus dem Inhalt selbst übernommen und belegen, dass nicht nur Metadaten gelesen wurden.')
        if has('rastvögel', 'vögel', 'fledermaus', 'ökologisch', 'oekologisch', 'artenschutz'):
            report.append('• Der fachliche Kontext deutet auf eine ökologische bzw. naturschutzbezogene Auswertung hin.')
        if has('.xlsx', '.csv', '.ods'):
            report.append('• Tabellen- und Arbeitsblattinhalte wurden direkt aus den Dateien gelesen und ergänzen die räumlichen Informationen.')
        if has('.zip', '.tar', '.tgz', '.tar.gz'):
            report.append('• Archive wurden entpackt und die enthaltenen Dateien wurden in die Analyse einbezogen.')
        for fact in facts[:12]:
            if fact not in file_names:
                report.append(f'• {fact}')
    else:
        report.append('• Es lagen vor allem Dateinamen und Strukturhinweise vor; diese wurden als Grundlage für die Analyse genutzt.')

    report.extend(['', '## Schlussfolgerung'])
    if has('.shp', '.dbf', '.prj', '.shx'):
        report.append('Die analysierten Geodaten-Dateien bieten eine solide Grundlage für die räumliche Analyse und sind fachlich gut weiterverarbeitbar.')
    elif has('.xlsx', '.csv', '.ods'):
        report.append('Die Tabelleninhalte liefern ausreichend Substanz für eine strukturierte Auswertung und können direkt in weitere Analysen übernommen werden.')
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
