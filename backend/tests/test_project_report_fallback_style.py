from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.project_report_fallback import build_project_report_fallback


def test_project_report_fallback_uses_three_sections_only():
    report = build_project_report_fallback(
        'Erstelle bitte einen Bericht aus dem Projektordner.',
        'Datei: a.txt\nInhalt A\nDatei: b.pdf\nInhalt B',
        'Mein Projekt',
    )

    assert '## Anfrage' not in report
    assert report.count('## Zusammenfassung') == 1
    assert report.count('## Analyse') == 1
    assert report.count('## Schluss') == 1
    assert report.index('## Zusammenfassung') < report.index('## Analyse') < report.index('## Schluss')


def test_project_report_fallback_avoids_bullet_lists_in_body():
    report = build_project_report_fallback(
        'Erstelle bitte einen Bericht.',
        'Datei: a.txt\n- Punkt 1\n- Punkt 2\nKontext',
        'Projekt',
    )

    body_lines = [line for line in report.splitlines() if line and not line.startswith('#')]
    assert not any(line.lstrip().startswith(('-', '•')) for line in body_lines)
