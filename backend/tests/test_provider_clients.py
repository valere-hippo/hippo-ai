from app.services.provider_clients import build_chat_completion_payload, model_uses_completion_tokens, resolve_provider_runtime


def test_model_uses_completion_tokens_for_gpt5_family():
    assert model_uses_completion_tokens('gpt-5.4-mini')
    assert model_uses_completion_tokens('openai/gpt-5.4-mini')
    assert not model_uses_completion_tokens('gpt-4o-mini')


def test_build_chat_completion_payload_switches_parameter_names():
    reasoning = build_chat_completion_payload('gpt-5.4-mini', [{'role': 'user', 'content': 'hi'}], max_tokens=1200, temperature=0.2)
    assert 'max_completion_tokens' in reasoning
    assert 'max_tokens' not in reasoning
    assert 'temperature' not in reasoning

    standard = build_chat_completion_payload('gpt-4o-mini', [{'role': 'user', 'content': 'hi'}], max_tokens=1200, temperature=0.2)
    assert 'max_tokens' in standard
    assert 'max_completion_tokens' not in standard
    assert 'temperature' not in standard


def test_resolve_provider_runtime_defaults_to_openai_provider():
    runtime = resolve_provider_runtime('qween')
    assert runtime.tag == 'qwen'
    assert runtime.model_name is not None
