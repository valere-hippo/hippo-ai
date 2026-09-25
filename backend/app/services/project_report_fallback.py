from __future__ import annotations


def build_project_report_fallback(question: str, project_files_context: str, project_name: str | None = None) -> str:
    title = (project_name or 'Projektbericht').strip() or 'Projektbericht'
    question_text = (question or '').strip() or 'Analyse der Projektdateien'
    context_text = (project_files_context or '').strip() or 'Kein Dateikontext verfügbar.'

    return (
        f"# {title}\n\n"
        "## Anfrage\n"
        f"{question_text}\n\n"
        "## Projektdateien und Analysekontext\n"
        f"{context_text}\n\n"
        "## Zusammenfassung\n"
        "- Die Dateien wurden aus dem Projektkontext zusammengetragen.\n"
        "- Diese Fassung wurde automatisch erzeugt, weil die Modellantwort nicht rechtzeitig verfügbar war.\n"
        "- Alle sichtbaren Inhalte aus dem Projektkontext sind oben dokumentiert.\n\n"
        "## Hinweis\n"
        "Wenn du möchtest, kann ich im nächsten Schritt eine verfeinerte Fassung mit stärkerer Gliederung, Tabelle der Dateien und separaten Beobachtungen pro Datei erzeugen."
    )
