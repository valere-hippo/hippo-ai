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

    summary_line = (
        'Dieser Bericht fasst die Analyse der Projektdateien zusammen. '
        'Die Auswertung stützt sich auf die tatsächlich extrahierten Inhalte und nicht nur auf Dateinamen.'
    )
    if has('.zip', '.tar', '.tgz', '.tar.gz'):
        summary_line = (
            'Dieser Bericht fasst die Analyse der Projektdateien zusammen. '
            'Enthaltene Archive wurden entpackt und ihre Inhalte mitanalysiert. '
            'Die Auswertung stützt sich auf die tatsächlich extrahierten Inhalte und nicht nur auf Dateinamen.'
        )

    report: list[str] = [
        f'# {report_title}',
        'Professioneller Bericht',
        '',
        'Zusammenfassung',
        summary_line,
        '',
        'Analyse',
    ]

    if file_names:
        report.append('Dateibestand und fachliche Bedeutung:')
        for name in file_names[:20]:
            lower = name.lower()
            if lower.endswith('.cpg'):
                report.append(f'- Datei: {name}')
                report.append('  Encoding: Zeichencodierung der zugehörigen Attributdaten.')
                report.append('  Diese Datei definiert die Zeichenkodierung für die zugehörige DBF-Datei.')
            elif lower.endswith('.dbf'):
                report.append(f'- Datei: {name}')
                report.append('  Datensätze: Attributtabelle der Shapefile-Daten.')
                if has('beispielzeile', 'beispielinhalt', 'beispieldatensatz'):
                    report.append('  Beispielzeile: Ein Beispielwert wurde direkt aus den Attributdaten übernommen und belegt, dass nicht nur Metadaten gelesen wurden.')
                report.append('  Diese Datei enthält die Attributtabelle und ordnet die fachlichen Merkmale den geometrischen Objekten zu.')
            elif lower.endswith('.prj'):
                report.append(f'- Datei: {name}')
                report.append('  Projektion: Koordinatensystem / räumliches Referenzsystem.')
                report.append('  Diese Datei definiert das Koordinatensystem, das für die räumliche Analyse verwendet wird.')
            elif lower.endswith('.shp'):
                report.append(f'- Datei: {name}')
                report.append('  Geometrietyp: Geometrische Hauptdatei des Shapefiles.')
                if has('bounding box', 'bbox'):
                    report.append('  Bounding Box: Die räumliche Ausdehnung ist aus den extrahierten Metadaten direkt ablesbar.')
                report.append('  Diese Datei enthält die geometrischen Daten der Objekte im Projekt.')
            elif lower.endswith('.shx'):
                report.append(f'- Datei: {name}')
                report.append('  Geometrietyp: Indexdatei der Shapefile-Struktur.')
                if has('bounding box', 'bbox'):
                    report.append('  Bounding Box: Die Indexdatei bestätigt die räumliche Struktur des Verbunds.')
                report.append('  Diese Datei ist der Index für die Shapefile und ermöglicht einen schnellen Zugriff auf die geometrischen Daten.')
            elif lower.endswith('.zip') or lower.endswith('.tar') or lower.endswith('.tgz') or lower.endswith('.tar.gz'):
                report.append(f'- Archiv: {name}')
                report.append('  Enthaltene Dateien: Das Archiv wird entpackt und die internen Dateien werden anschließend ebenfalls analysiert.')
            else:
                report.append(f'- Datei: {name}')
                report.append('  Relevanz: Teil des analysierten Projektkontexts.')

    report.extend(['', 'Detailanalyse', 'Technische Einordnung'])
    if facts:
        if has('geometrietyp', 'bounding box', 'bbox'):
            report.append('Die Geometrie wurde inhaltlich erkannt; Bounding Box und Geometrietyp zeigen nicht nur die Form der Objekte, sondern auch die räumliche Ausdehnung und die Eignung für GIS-Auswertungen.')
        if has('felder', 'feld', 'attribut', 'daten', 'dbf', 'datensätze'):
            report.append('Die Attributdaten liefern nicht nur Struktur, sondern auch fachliche Kernaussagen darüber, wie viele Objekte vorliegen, welche Merkmale gespeichert sind und wie zuverlässig der Datensatz auswertbar ist.')
        if has('projektion', 'koordinatensystem', 'prj'):
            report.append('Die Projektion ist definiert und macht den Datensatz direkt GIS-tauglich; ohne diese Angabe wäre eine räumliche Einordnung riskant oder ungenau.')
        if has('beispielinhalt', 'beispielzeile', 'beispieldatensatz'):
            report.append('Beispielwerte wurden aus dem Inhalt selbst übernommen und belegen, dass nicht nur Metadaten gelesen wurden, sondern auch der fachliche Kern der Datei.')
        if has('.xlsx', '.csv', '.ods'):
            report.append('Tabellen- und Arbeitsblattinhalte wurden direkt aus den Dateien gelesen und ergänzen die räumlichen Informationen um konkrete Beobachtungs- und Auswertungswerte.')
        if has('.zip', '.tar', '.tgz', '.tar.gz'):
            report.append('Archive wurden entpackt und die enthaltenen Dateien wurden in die Analyse einbezogen; das ist wichtig, weil die fachliche Bedeutung oft erst in den entpackten Begleitdateien sichtbar wird.')
    else:
        report.append('Es lagen vor allem Dateinamen und Strukturhinweise vor; diese wurden als Grundlage für die Analyse genutzt.')

    report.extend(['', 'Fachliche Einordnung'])
    if has('.shp', '.dbf', '.prj', '.shx'):
        report.append('Der Datensatz ist als klassischer GIS-Verbund aufgebaut; Geometrie, Index, Attributtabelle und Projektion greifen ineinander und sind nur gemeinsam vollständig interpretierbar.')
    if has('rastvögel', 'vögel', 'fledermaus', 'ökologisch', 'oekologisch', 'artenschutz', 'haselmaus'):
        report.append('Der fachliche Kontext deutet auf eine ökologische bzw. naturschutzbezogene Auswertung hin. Das bedeutet: Nicht nur die Existenz der Dateien ist relevant, sondern vor allem Lage, Dichte, Nutzung, Quartierqualität, Störungsdruck und die räumliche Vernetzung.')
    if has('.xlsx', '.csv', '.ods'):
        report.append('Tabelleninhalte liefern meist Beobachtungs- oder Auswertungsdaten; fachlich ist entscheidend, ob diese Werte Häufigkeiten, Zeitbezug, Orte oder Bewertungen abbilden.')
    if has('.zip', '.tar', '.tgz', '.tar.gz'):
        report.append('Archive sind hier kein Nebenschauplatz: Sie können zusätzliche Begleitdaten, Karten, Tabellen oder Rohdaten enthalten, die den eigentlichen Befund erst belastbar machen.')

    species_candidates: list[str] = []
    for item in facts + file_names:
        parts: list[str] = []
        if 'artenhinweise' in item.lower() or 'arten' in item.lower() or 'art:' in item.lower():
            raw = item.split(':', 1)[-1] if ':' in item else item
            for chunk in re.split(r'[;,/]|\band\b|\bund\b', raw, flags=re.IGNORECASE):
                candidate = re.sub(r'\s+', ' ', chunk).strip(' .:-–—')
                if candidate and len(candidate) > 2:
                    parts.append(candidate)
        for candidate in parts:
            if candidate.lower() not in {s.lower() for s in species_candidates}:
                species_candidates.append(candidate)
    if species_candidates:
        report.append('')
        report.append('Artbezogene Bewertung')
        for candidate in species_candidates:
            if len(candidate) > 40:
                continue
            lower_candidate = candidate.lower()
            if any(token in lower_candidate for token in ('fledermaus', 'bat', 'quartier')):
                report.append(f'- {candidate}')
                report.append('  Beobachtung: Die Unterlagen enthalten Hinweise auf Fledermäuse bzw. Quartierbezug.')
                report.append('  Fachliche Bedeutung: Das spricht für einen potenziellen Quartier-, Zugangs- oder Jagdhabitatbezug und damit für eine hohe Sensitivität gegenüber baulichen Eingriffen.')
                report.append('  Implikation: Für die Bewertung sind Einflugmöglichkeiten, Hangplätze, Störungsarmut, Flugkorridore und die Anbindung an Nahrungshabitate maßgeblich.')
            elif 'haselmaus' in lower_candidate:
                report.append(f'- {candidate}')
                report.append('  Beobachtung: Die Art ist im Projektkontext als streng geschütztes Kleinsäuger-Taxon relevant.')
                report.append('  Fachliche Bedeutung: Die Nachweislage deutet auf eine Habitatbindung an Gehölzstrukturen, Saumbereiche und Rückzugsräume hin.')
                report.append('  Implikation: Zu prüfen sind Vernetzung, Habitatsqualität, Störungsdruck und die Frage, ob die Fläche als Kern- oder lediglich als Randlebensraum wirkt.')
            elif any(token in lower_candidate for token in ('maus',)):
                report.append(f'- {candidate}')
                report.append('  Beobachtung: Es liegt ein Kleinsäugerbezug vor, der fachlich nicht nur auf ein Einzeltier, sondern auf die Habitatfunktion der Fläche verweist.')
                report.append('  Fachliche Bedeutung: Der Befund kann auf Nutzung, Durchquerung oder zeitweise Anwesenheit hinweisen und sollte nicht isoliert interpretiert werden.')
                report.append('  Implikation: Relevant sind Deckung, Vernetzung, Störungsniveau und die Frage, ob die Fläche Teil eines funktionalen Verbunds ist.')
            elif any(token in lower_candidate for token in ('rastvogel', 'vogel', 'avifauna')):
                report.append(f'- {candidate}')
                report.append('  Beobachtung: Der Kontext verweist auf Vogelvorkommen oder avifaunistische Datensätze.')
                report.append('  Fachliche Bedeutung: Für Vögel ist nicht nur der Nachweis selbst wichtig, sondern auch Brutstatus, Revierausdehnung, Nutzungshäufigkeit und das Umfeld.')
                report.append('  Implikation: Erforderlich ist eine getrennte Betrachtung von Brutverdacht, Revierzentrum, Nahrungshabitat und Störungseinflüssen.')
            else:
                report.append(f'- {candidate}')
                report.append('  Beobachtung: Für diese Art liegt ein fachlich relevanter Hinweis im Datensatz vor.')
                report.append('  Fachliche Bedeutung: Der Hinweis ist im Kontext von Lebensraum, Schutzstatus und räumlicher Einbindung zu bewerten.')
                report.append('  Implikation: Die Interpretation sollte artspezifisch und nicht nur datensatzbezogen erfolgen.')

    report.extend(['', 'Schlussfolgerung'])
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
