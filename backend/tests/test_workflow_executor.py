import asyncio
from types import SimpleNamespace

import app.services.workflow_executor as workflow_executor


def test_task_source_prefixes_cover_common_input_kinds():
    image_task = SimpleNamespace(input_kind='images', instruction='Analyse die Bilder', title='Bilder')
    geo_task = SimpleNamespace(input_kind='geodata', instruction='Analysiere die Koordinaten', title='Geodaten')
    text_task = SimpleNamespace(input_kind='text', instruction='Analysiere die Texte', title='Texte')

    assert 'image' in workflow_executor._task_source_prefixes(image_task)
    assert 'geo' in workflow_executor._task_source_prefixes(geo_task)
    assert 'text' in workflow_executor._task_source_prefixes(text_task)


def test_build_task_file_context_falls_back_when_prefix_filter_finds_nothing():
    project = SimpleNamespace(id=7, watched_folder='/data/shared-project', pcloud_path=None, pcloud_folder_id=None)
    task = SimpleNamespace(input_kind='images', instruction='Analyse die Bilder', title='Bilder')
    calls = []

    async def fake_build_project_files_context(project_arg, max_files=None, include_previews=True, question=None, source_prefixes=None):
        calls.append(source_prefixes)
        if source_prefixes:
            return 'Im lokalen Projektordner konnten aktuell noch keine Dateien zuverlässig ausgelesen werden.'
        return 'FULL-CONTEXT'

    original = workflow_executor.build_project_files_context
    try:
        workflow_executor.build_project_files_context = fake_build_project_files_context
        class Result:
            def scalar_one_or_none(self):
                return project
        class FakeDB:
            async def execute(self, stmt):
                return Result()
        result = asyncio.run(workflow_executor.build_task_file_context(FakeDB(), SimpleNamespace(project_id=7), task))
    finally:
        workflow_executor.build_project_files_context = original

    assert result == 'FULL-CONTEXT'
    assert calls == [workflow_executor._task_source_prefixes(task), None]
