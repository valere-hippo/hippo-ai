from app.services.project_report_fallback import build_project_report_fallback, _is_valid_report_text


def test_build_project_report_fallback_preserves_structured_model_report():
    model_report = """## Zusammenfassung
- Punkt A

## Analyse
- Punkt B

## Schluss
- Punkt C"""

    result = build_project_report_fallback(
        question="Analysiere die Dateien im Projekt",
        project_files_context=model_report,
        project_name="Bitburg Transekt",
    )

    assert result.startswith("# Bitburg Transekt")
    assert "## Zusammenfassung" in result
    assert "Punkt A" in result
    assert "## Analyse" in result
    assert "## Schluss" in result


def test_build_project_report_fallback_still_builds_from_context_when_not_a_report():
    context = """
Geodatenpaket für 'bitburg':
- Geometrietyp: 5
- Bounding Box: 1.0, 2.0, 3.0, 4.0
- Felder: NAME (C)
- Datensätze: 2
- Beispielinhalt: NAME=Demo
""".strip()

    result = build_project_report_fallback(
        question="Analysiere die Dateien im Projekt",
        project_files_context=context,
        project_name="Bitburg Transekt",
    )

    assert "## Zusammenfassung" in result
    assert "Geodatenpaket für" in result
    assert "Geometrietyp" in result
    assert "## Schluss" in result


def test_is_valid_report_text_rejects_status_only_replies():
    assert not _is_valid_report_text("Ich werde die geodatenbezogenen Dateien analysieren. Dies umfasst die Dateien .cpg, .dbf, .prj und .shx.")
    assert not _is_valid_report_text("Ich habe die Dateien analysiert und einen Bericht erstellt.")
    assert _is_valid_report_text("## Zusammenfassung\n- Punkt A\n\n## Analyse\n- Punkt B\n\n## Schluss\n- Punkt C\n- Geometrietyp: 5")
