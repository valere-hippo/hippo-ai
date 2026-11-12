from app.services.workflow_planner import build_workflow_metadata, has_workflow_markers, normalize_model_tag, parse_workflow_message


def test_parse_workflow_message_splits_parallel_tasks_and_final_synthesis():
    tasks = parse_workflow_message(
        """Analyse die Bilder #deepseek #parallel
Analyse die geographischen Koordinaten #qwen #parallel
Analyse die Texte #tencent #parallel
Erstelle danach den Bericht #openai"""
    )

    assert [task.task_key for task in tasks] == ["t1", "t2", "t3", "t4"]
    assert [task.model_tag for task in tasks] == ["deepseek", "qwen", "tencent", "openai"]
    assert [task.execution_mode for task in tasks[:3]] == ["parallel", "parallel", "parallel"]
    assert tasks[3].depends_on == ["t1", "t2", "t3"]
    assert tasks[3].execution_mode == "sequential"


def test_parse_workflow_message_supports_after_dependencies():
    tasks = parse_workflow_message(
        """Analyse Bilder #deepseek
Analysiere Geodaten #qwen #after:t1
Schreibe den Bericht #claude #after:t1 #after:t2"""
    )

    assert tasks[1].depends_on == ["t1"]
    assert tasks[1].execution_mode == "sequential"
    assert tasks[2].depends_on == ["t1", "t2"]
    assert tasks[2].model_tag == "claude"


def test_build_workflow_metadata_sets_default_final_model_tag():
    metadata = build_workflow_metadata("Analysiere Bilder #deepseek\nSchreibe den Bericht")
    assert metadata["status"] == "pending"
    assert metadata["final_model_tag"] == "openai"
    assert len(metadata["tasks"]) == 2


def test_normalize_model_tag_supports_qween_alias():
    assert normalize_model_tag("qween") == "qwen"
    assert normalize_model_tag("#deepseek") == "deepseek"


def test_has_workflow_markers_detects_model_tags_and_dependencies():
    assert has_workflow_markers("Analyse die Bilder #deepseek #parallel")
    assert has_workflow_markers("Bitte #after:t1 den Bericht schreiben")
    assert not has_workflow_markers("Bitte die Bilder analysieren ohne Tags")
