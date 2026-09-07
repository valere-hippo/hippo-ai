from types import SimpleNamespace
from typing import Any

from app.services.project_skills import format_project_skills_context, rank_project_skills_for_query
from app.services.embedding_context import _dedupe_embedding_items, format_embedding_context


def test_rank_project_skills_for_query_prioritizes_relevant_names():
    skills: list[Any] = [
        SimpleNamespace(name='Write reports', description='Generate PDFs', instructions='Always use structure', is_enabled=True, project_id=None),
        SimpleNamespace(name='Translate', description='Language support', instructions='Translate text', is_enabled=True, project_id=None),
        SimpleNamespace(name='Archive', description='Store files', instructions='Archive documents', is_enabled=True, project_id=12),
    ]

    ranked = rank_project_skills_for_query(skills, 'Please write a report about project files', limit=2)

    assert [skill.name for skill in ranked] == ['Write reports', 'Archive']


def test_format_project_skills_context_trims_to_relevant_skills():
    skills: list[Any] = [
        SimpleNamespace(name='Write reports', description='Generate PDFs', instructions='Always use structure\nAdd a conclusion', is_enabled=True, project_id=None),
        SimpleNamespace(name='Translate', description='Language support', instructions='Translate text', is_enabled=True, project_id=None),
    ]

    context = format_project_skills_context(skills, query='write a report', limit=1)

    assert 'Write reports' in context
    assert 'Translate' not in context
    assert 'Anweisung:' in context


def test_dedupe_embedding_items_prefers_highest_score_and_keeps_source():
    items = [
        {'id': 1, 'text': 'Shared insight', 'score': 0.63, 'source': 'local'},
        {'id': 1, 'text': 'Shared insight', 'score': 0.91, 'source': 'remote'},
        {'id': 2, 'text': 'Project note', 'score': 0.82, 'source': 'local'},
    ]

    merged = _dedupe_embedding_items(items, limit=2)

    assert len(merged) == 2
    assert merged[0]['score'] == 0.91
    assert merged[0]['source'] == 'remote'


def test_format_embedding_context_shows_scores_and_sources():
    context = format_embedding_context([
        {'text': 'Useful note', 'score': 0.88, 'source': 'local'},
    ])

    assert '[0.88]' in context
    assert '(local)' in context
    assert 'Useful note' in context
