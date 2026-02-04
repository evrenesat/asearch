from asky.config import MODELS, SYSTEM_PROMPT


def test_models_config():
    assert isinstance(MODELS, dict)
    assert len(MODELS) > 0
    for model_key, config in MODELS.items():
        assert "id" in config
        assert "context_size" in config


def test_system_prompt_params():
    # Verify strings are importable and non-empty
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 0


def test_default_context_size():
    from asky.config import DEFAULT_CONTEXT_SIZE

    assert isinstance(DEFAULT_CONTEXT_SIZE, int)
    assert DEFAULT_CONTEXT_SIZE > 0


def test_invalid_config_exits(tmp_path):
    """Ensure invalid TOML raises SystemExit."""
    from unittest.mock import patch
    from asky.config.loader import load_config
    import pytest

    # Create invalid config
    config_dir = tmp_path / "asky"
    config_dir.mkdir()
    config_file = config_dir / "config.toml"
    config_file.write_text("invalid_toml = [")

    with patch("asky.config.loader._get_config_dir", return_value=config_dir):
        with pytest.raises(SystemExit) as excinfo:
            load_config()
        assert excinfo.value.code == 1
