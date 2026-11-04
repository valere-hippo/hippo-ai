from app.services.project_access import build_default_source_scope


def test_build_default_source_scope_enables_all_project_folders():
    scope = build_default_source_scope('/data/project-a\n/data/project-b')

    assert scope == {
        'source_folders': ['/data/project-a', '/data/project-b'],
        'consented': True,
    }


def test_build_default_source_scope_returns_none_for_empty_input():
    assert build_default_source_scope('') is None
