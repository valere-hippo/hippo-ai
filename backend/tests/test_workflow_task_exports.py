from app.services.workflow_planner import build_workflow_task_generated_file


def test_build_workflow_task_generated_file_uses_task_specific_filename():
    task = {
        'task_key': 't1',
        'title': 'Analyse Bilder',
        'model_tag': 'deepseek',
        'provider': 'deepseek',
        'content': 'Bildanalyse',
    }

    data, mime_type, filename = build_workflow_task_generated_file(task, workflow_id=99)

    assert filename == 'workflow_99_t1_deepseek.docx'
    assert mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    assert data[:4] == b'PK\x03\x04'
