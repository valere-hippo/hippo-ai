import asyncio
from datetime import datetime
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


def test_build_project_files_context_uses_multi_pass_model_synthesis_when_context_is_large():
    project = SimpleNamespace(
        watched_folder='/data/shared-project',
        pcloud_path=None,
        pcloud_folder_id=None,
    )
    large_text = 'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega\n' * 200
    fake_files = [
        SimpleNamespace(
            filename=f'file-{index}.txt',
            size=len(large_text),
            modified_at=datetime(2024, 1, index if index < 28 else 28),
            storage='local',
        )
        for index in range(1, 7)
    ]
    calls = []

    class FakeResponse:
        def __init__(self, content):
            self._content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {'choices': [{'message': {'content': self._content}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls = calls

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({'url': url, 'messages': json.get('messages', []) if isinstance(json, dict) else []})
            user_content = ''
            if isinstance(json, dict) and json.get('messages'):
                user_content = str(json['messages'][-1].get('content') or '')
            if 'zusammengefassten Batches' in user_content or 'konsolidierst mehrere Zusammenfassungen' in user_content:
                return FakeResponse('FINAL-SYNTHESIS')
            return FakeResponse(f'BATCH-SUMMARY-{len(calls)}')

    original_list_project_files = project_storage.list_project_files
    original_read_project_file = project_storage.read_project_file
    original_httpx_client = project_storage.httpx.AsyncClient
    original_api_url = project_storage.settings.hippo_api_url
    original_api_key = project_storage.settings.hippo_api_key
    try:
        project_storage.list_project_files = lambda _project, source_prefixes=None: fake_files
        project_storage.read_project_file = lambda _project, filename: (large_text.encode('utf-8'), 'text/plain', 'local')
        project_storage.httpx.AsyncClient = FakeClient
        project_storage.settings.hippo_api_url = 'https://example.com/v1/chat/completions'
        project_storage.settings.hippo_api_key = ''

        result = asyncio.run(
            project_storage.build_project_files_context(
                project,
                question='Bitte fasse die Dateien zusammen',
                source_prefixes=['/data/shared-project'],
            )
        )
    finally:
        project_storage.list_project_files = original_list_project_files
        project_storage.read_project_file = original_read_project_file
        project_storage.httpx.AsyncClient = original_httpx_client
        project_storage.settings.hippo_api_url = original_api_url
        project_storage.settings.hippo_api_key = original_api_key

    assert result == 'FINAL-SYNTHESIS'
    assert len(calls) >= 2


def test_list_project_files_filters_by_source_prefixes():
    project = SimpleNamespace(
        watched_folder='/data/shared-project',
        pcloud_path=None,
        pcloud_folder_id=None,
    )
    fake_files = [
        SimpleNamespace(filename='images/a.png', size=10, modified_at=datetime(2024, 1, 1), storage='local'),
        SimpleNamespace(filename='texts/b.txt', size=10, modified_at=datetime(2024, 1, 1), storage='local'),
    ]

    original_iter = project_storage._iter_local_project_files
    try:
        project_storage._iter_local_project_files = lambda _project: fake_files
        result = project_storage.list_project_files(project, source_prefixes=['images/'])
    finally:
        project_storage._iter_local_project_files = original_iter

    assert [item.filename for item in result] == ['images/a.png']
