from app.services.workflow_planner import build_workflow_execution_summary, summarize_workflow_execution


def test_build_workflow_execution_summary_includes_provider_results():
    plan = {
        'workflow_id': 42,
        'final_model_tag': 'openai',
        'tasks': [
            {'task_key': 't1', 'title': 'Analyse Bilder', 'instruction': 'Analyse Bilder', 'model_tag': 'deepseek'},
            {'task_key': 't2', 'title': 'Bericht', 'instruction': 'Bericht', 'model_tag': 'openai'},
        ],
    }
    execution = {
        'workflow_id': 42,
        'status': 'completed',
        'results': {
            't1': {'provider': 'deepseek', 'model': 'deepseek-chat', 'content': 'Bildanalyse'},
            't2': {'provider': 'openai', 'model': 'gpt-5.4-mini', 'content': 'Endbericht'},
        },
    }

    summary = build_workflow_execution_summary(plan, execution)

    assert summary['workflow_id'] == 42
    assert summary['status'] == 'completed'
    assert summary['task_count'] == 2
    assert summary['tasks'][0]['provider'] == 'deepseek'
    assert summary['tasks'][1]['is_final'] is True
    assert summary['final_result']['content'] == 'Endbericht'
    text = summarize_workflow_execution(plan, execution)
    assert 'Bildanalyse' in text
    assert 'Endbericht' in text
