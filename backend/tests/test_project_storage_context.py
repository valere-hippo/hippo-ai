import asyncio
from types import SimpleNamespace

import app.services.project_storage as project_storage


def test_build_project_files_context_does_not_claim_empty_when_scan_is_uninformative():
    project = SimpleNamespace(
        watched_folder='/data/shared-project',
        pcloud_path=None,
        pcloud_folder_id=None,
    )

    original_list_project_files = project_storage.list_project_files
    original_tree_context = project_storage._build_local_project_tree_context
    try:
        project_storage.list_project_files = lambda _project, source_prefixes=None: []
        project_storage._build_local_project_tree_context = lambda _project: ''

        result = asyncio.run(
            project_storage.build_project_files_context(
                project,
                question='Welche Dateien sind im gemeinsamen Ordner?',
                source_prefixes=['/data/shared-project'],
            )
        )
    finally:
        project_storage.list_project_files = original_list_project_files
        project_storage._build_local_project_tree_context = original_tree_context

    assert 'leer oder die lokale Synchronisierung ist noch nicht abgeschlossen' not in result
    assert 'leer' not in result.lower()
    assert '/data/shared-project' in result
