from asky.config import MODELS, TOOLS, SYSTEM_PROMPT


def test_models_config():
    assert isinstance(MODELS, dict)
    assert len(MODELS) > 0
    for model_key, config in MODELS.items():
        assert "id" in config
        assert "context_size" in config


def test_tools_config():
    assert isinstance(TOOLS, list)
    assert len(TOOLS) > 0
    for tool in TOOLS:
        assert "type" in tool
        assert "function" in tool
        assert "name" in tool["function"]


def test_system_prompt_params():
    # Verify strings are importable and non-empty
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 0


def test_default_context_size():
    from asky.config import DEFAULT_CONTEXT_SIZE

    assert isinstance(DEFAULT_CONTEXT_SIZE, int)
    assert DEFAULT_CONTEXT_SIZE > 0
