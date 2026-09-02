from types import SimpleNamespace

from app.services.project_skills import format_project_skills_context


def test_format_project_skills_context_only_lists_enabled_skills():
    skills = [
        SimpleNamespace(name="Analyse", description="Analyse de projet", instructions="1. Lire\n2. Résumer", is_enabled=True),
        SimpleNamespace(name="Brouillon", description="Inactif", instructions="Ignorer", is_enabled=False),
    ]

    result = format_project_skills_context(skills)

    assert "Aktive Projektskills" in result
    assert "Analyse" in result
    assert "Brouillon" not in result
    assert "1. Lire" in result
