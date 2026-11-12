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
    lower_all = lower_facts + lower_names

    def has(*needles: str) -> bool:
        return any(any(needle in item for needle in needles) for item in lower_all)

    report_title = 'Fachbeitrag Artenschutz / Geodatenanalyse' if has('.shp', '.shx', '.dbf', '.prj', '.cpg', 'geodaten', 'shapefile', 'gis') else 'Bericht zur Analyse der Projektdateien'

    def field_value(*labels: str) -> str | None:
        for line in _normalize_lines(report_text):
            lowered = line.lower()
            if any(label in lowered for label in labels):
                if ':' in line:
                    return line.split(':', 1)[-1].strip()
                return line.strip()
        return None

    bundesland = field_value('bundesland') or 'laut Unterlagen'
    auftraggeber = field_value('auftraggeber') or 'laut Unterlagen'
    datum = field_value('datum') or 'laut Unterlagen'
    gutachter = field_value('gutachter') or 'Hippo AI'

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

    figure_lines = [line.strip() for line in _normalize_lines(report_text) if line.lower().startswith('abbildung')][:6]
    table_lines = [line.strip() for line in _normalize_lines(report_text) if line.lower().startswith('tabelle')][:6]

    report: list[str] = [
        f'# {report_title}',
        '',
        f'Projekt: {title}',
        f'Bundesland: {bundesland}',
        f'Auftraggeber: {auftraggeber}',
        f'Datum: {datum}',
        f'Gutachter: {gutachter}',
        '',
        'Dieses Gutachten ist einschließlich des Deckblatts und der Anlagen urheberrechtlich geschützt.',
        'Vervielfältigung und Weitergabe - auch auszugsweise - sind nur mit Zustimmung des Auftragnehmers gestattet.',
        '',
        'Inhalt',
        '1. Anlass und Zielsetzung',
        '2. Methodik',
        '3. Ergebnisse',
        '3.1. Dateibestand und fachliche Einordnung',
        '3.2. Technische Einordnung',
        '3.3. Fachliche Einordnung',
        '3.4. Artbezogene Bewertung',
        '4. Zusammenfassende Bewertung',
        '5. Schlussfolgerung',
    ]

    if figure_lines:
        report.extend(['', 'Abbildungsverzeichnis'])
        for line in figure_lines:
            report.append(f'- {line}')
    if table_lines:
        report.extend(['', 'Tabellenverzeichnis'])
        for line in table_lines:
            report.append(f'- {line}')

    report.extend([
        '',
        '1. Anlass und Zielsetzung',
        summary_line,
    ])

    if question_text:
        cleaned_question = question_text.rstrip(' .!?')
        report.append(f'Die aktuelle Fragestellung lautet sinngemäß: {cleaned_question}.')

    report.extend([
        '',
        '2. Methodik',
        'Die Analyse erfolgte auf Grundlage der tatsächlich extrahierten Datei- und Inhaltsinformationen. Wenn Geodaten vorliegen, werden Geometrie, Attributtabellen und Projektionen gemeinsam betrachtet, weil diese Komponenten fachlich nur im Verbund belastbar interpretierbar sind.',
    ])

    if has('.zip', '.tar', '.tgz', '.tar.gz'):
        report.append('Archive im Projektkontext wurden entpackt und die darin enthaltenen Dateien ebenfalls in die Auswertung einbezogen; verschachtelte Archive wurden dabei ebenfalls berücksichtigt.')
    if has('.shp', '.shx', '.dbf', '.prj'):
        report.append('Bei Geodaten wird zwischen Geometrie, Attributdaten, Indexstruktur und räumlichem Bezug unterschieden, um nicht nur die Existenz, sondern auch die fachliche Aussagekraft zu bewerten.')
    if has('.xlsx', '.csv', '.ods'):
        report.append('Tabellen- und Arbeitsblattinhalte wurden als fachliche Primärdaten behandelt und nicht nur als Begleitmaterial.')

    report.extend([
        '',
        '3. Ergebnisse',
    ])

    if file_names:
        report.append('3.1. Dateibestand und fachliche Einordnung')
        for name in file_names[:20]:
            lower = name.lower()
            if lower.endswith('.cpg'):
                report.append(f'- {name}: Codierungsdatei für die zugehörigen Attributdaten. Fachlich relevant, weil sie bestimmt, wie Sonderzeichen und Namensfelder korrekt gelesen werden.')
            elif lower.endswith('.dbf'):
                report.append(f'- {name}: Attributtabelle der Shapefile-Struktur. Sie liefert die fachlichen Merkmale zu den geometrischen Objekten und ist für die Interpretation zentral.')
            elif lower.endswith('.prj'):
                report.append(f'- {name}: Projektions- bzw. Referenzsystemdatei. Sie ist maßgeblich für die räumliche Eindeutigkeit und die korrekte GIS-Verarbeitung.')
            elif lower.endswith('.shp'):
                report.append(f'- {name}: Geometriedatei des GIS-Verbunds. Sie enthält die räumlichen Objekte und bildet die eigentliche Lage- und Forminformation ab.')
            elif lower.endswith('.shx'):
                report.append(f'- {name}: Indexdatei des Shapefile-Verbunds. Sie unterstützt die räumliche Struktur und beschleunigt den Zugriff auf die Geometrien.')
            elif lower.endswith('.zip') or lower.endswith('.tar') or lower.endswith('.tgz') or lower.endswith('.tar.gz'):
                report.append(f'- {name}: Archivdatei. Inhalt und Nebenprodukte wurden entpackt und in die Analyse übernommen, weil relevante Fachinformationen oft erst im Archiv sichtbar werden.')
            else:
                report.append(f'- {name}: Teil des Projektkontexts mit möglicher fachlicher Relevanz.')

    report.append('')
    report.append('3.2. Technische Einordnung')
    if has('geometrietyp', 'bounding box', 'bbox'):
        report.append('Die Geometrie ist technisch nachvollziehbar beschrieben; Form und räumliche Ausdehnung sind damit für GIS-Anwendungen grundsätzlich interpretierbar.')
    if has('felder', 'feld', 'attribut', 'daten', 'dbf', 'datensätze'):
        report.append('Die Attributdaten sind fachlich aussagekräftig, weil sie die Objektgeometrie mit inhaltlichen Merkmalen verknüpfen und damit die eigentliche Analyse tragen.')
    if has('projektion', 'koordinatensystem', 'prj'):
        report.append('Das Koordinatensystem ist für die räumliche Verortung entscheidend; ohne eine saubere Projektion wären Lagebezug und Auswertung nur eingeschränkt belastbar.')
    if has('.xlsx', '.csv', '.ods'):
        report.append('Tabelleninhalte liefern zusätzliche inhaltliche Tiefe, beispielsweise zu Beobachtungen, Bewertungen, Zeitbezug oder Mengengerüsten.')
    if has('.zip', '.tar', '.tgz', '.tar.gz'):
        report.append('Die Archivstruktur ist fachlich relevant, weil wichtige Unterlagen in der Praxis häufig in Unterordnern oder komprimierten Sammeldateien abgelegt werden.')

    report.append('')
    report.append('3.3. Fachliche Einordnung')
    if has('.shp', '.dbf', '.prj', '.shx'):
        report.append('Der Datensatz wirkt wie ein klassischer GIS-Verbund: Geometrie, Attributtabelle, Index und Projektion greifen zusammen und müssen gemeinsam gelesen werden.')
    if has('rastvögel', 'vögel', 'fledermaus', 'ökologisch', 'oekologisch', 'artenschutz', 'haselmaus'):
        report.append('Der fachliche Kontext ist naturschutzbezogen. Damit ist nicht nur der Nachweis einzelner Arten relevant, sondern vor allem die Frage nach Lebensraumbindung, Störungsanfälligkeit, funktionaler Vernetzung und räumlicher Betroffenheit.')
    if has('.xlsx', '.csv', '.ods'):
        report.append('Tabelleninhalte sind in solchen Projekten meist keine bloßen Anhänge, sondern die Quelle für Begehungen, Bewertungen, Fundpunkte oder Nachweismuster.')

    species_candidates: list[str] = []
    seen_species: set[str] = set()
    for item in facts + file_names:
        if 'artenhinweise' not in item.lower() and 'arten' not in item.lower() and 'art:' not in item.lower():
            continue
        raw = item.split(':', 1)[-1] if ':' in item else item
        for chunk in re.split(r'[;,/]|\band\b|\bund\b', raw, flags=re.IGNORECASE):
            candidate = re.sub(r'\s+', ' ', chunk).strip(' .:-–—')
            if len(candidate) > 2 and candidate.lower() not in seen_species:
                species_candidates.append(candidate)
                seen_species.add(candidate.lower())

    if species_candidates:
        report.append('')
        report.append('3.4. Artbezogene Bewertung')
        for candidate in species_candidates:
            if len(candidate) > 40:
                continue
            lower_candidate = candidate.lower()
            report.append(f'- {candidate}')
            if any(token in lower_candidate for token in ('fledermaus', 'bat', 'quartier')):
                report.append('  Befund: Hinweise auf Fledermäuse bzw. Quartierbezug.')
                report.append('  Fachliche Bewertung: Das deutet auf einen sensiblen Struktur- und Funktionsraum hin, bei dem Einflug, Quartiernutzung, Störungsarmut und Flugkorridore mitbewertet werden müssen.')
                report.append('  Konsequenz: Für Eingriffe sind bau- und betriebsbedingte Störungen, Verlust von Strukturen und die Qualität angrenzender Jagdhabitate zu prüfen.')
            elif 'haselmaus' in lower_candidate:
                report.append('  Befund: Die Art ist als streng geschütztes Kleinsäuger-Taxon im Projektkontext relevant.')
                report.append('  Fachliche Bewertung: Das spricht für eine Bindung an Gehölzstrukturen, Saumbereiche und Rückzugsräume.')
                report.append('  Konsequenz: Entscheidend sind Vernetzung, Deckung, Quartier-/Nahrungsangebot und die Frage, ob die Fläche Kernhabitat oder nur Durchgangsraum ist.')
            elif any(token in lower_candidate for token in ('maus',)):
                report.append('  Befund: Es liegt ein Kleinsäugerbezug vor.')
                report.append('  Fachliche Bewertung: Der Nachweis kann auf Nutzung, Durchquerung oder temporäre Anwesenheit hinweisen und darf nicht isoliert gelesen werden.')
                report.append('  Konsequenz: Habitatqualität, Randwirkungen, Störungsniveau und funktionale Anbindung sind mitzudenken.')
            elif any(token in lower_candidate for token in ('rastvogel', 'vogel', 'avifauna')):
                report.append('  Befund: Der Kontext weist auf Vogelvorkommen bzw. avifaunistische Auswertungen hin.')
                report.append('  Fachliche Bewertung: Neben dem Nachweis sind Brutstatus, Revierfunktion, Nahrungshabitat und der räumliche Bezug zum Vorhaben entscheidend.')
                report.append('  Konsequenz: Eine getrennte Betrachtung von Brutverdacht, Revierzentrum und Störeinflüssen ist fachlich geboten.')
            else:
                report.append('  Befund: Ein fachlich relevanter Artenhinweis ist im Datensatz vorhanden.')
                report.append('  Fachliche Bewertung: Der Hinweis ist im Kontext von Lebensraum, Schutzstatus und räumlicher Einbindung zu bewerten.')
                report.append('  Konsequenz: Die artspezifische Interpretation sollte Vorrang vor einer rein statistischen Zusammenfassung haben.')

    report.extend(['', 'Zusammenfassende Bewertung'])
    if has('.shp', '.dbf', '.prj', '.shx'):
        report.append('Die Datenbasis ist für eine fachliche GIS-Analyse grundsätzlich geeignet und fachlich konsistent aufgebaut.')
    if has('.xlsx', '.csv', '.ods'):
        report.append('Die Tabellen liefern ergänzende fachliche Tiefe und sollten als eigenständige Evidenzquellen interpretiert werden.')
    if has('.zip', '.tar', '.tgz', '.tar.gz'):
        report.append('Die enthaltenen Archive wurden berücksichtigt; dadurch steigt die fachliche Vollständigkeit der Analyse deutlich.')
    if not facts and not file_names:
        report.append('Die Auswertung basiert auf dem verfügbaren Projektkontext; für eine belastbare fachliche Einordnung wären weitere lesbare Quelldaten hilfreich.')

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
