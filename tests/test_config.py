import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def test_settings_have_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "SceneChoice"
    assert settings.app_env == "development"
    assert settings.debug is False
    assert settings.deepseek_api_key is None


def test_settings_read_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("SCENECHOICE_APP_ENV", "testing")
    monkeypatch.setenv("SCENECHOICE_DEBUG", "true")
    monkeypatch.setenv("SCENECHOICE_DEEPSEEK_API_KEY", "test-secret")

    settings = Settings(_env_file=None)

    assert settings.app_env == "testing"
    assert settings.debug is True
    assert isinstance(settings.deepseek_api_key, SecretStr)
    assert settings.deepseek_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deepseek_timeout_seconds", 0),
        ("deepseek_max_tokens", 255),
        ("deepseek_max_tokens", 8193),
        ("story_planning_max_attempts", 0),
        ("story_planning_max_attempts", 6),
        ("story_planning_retry_base_seconds", -1),
        ("story_planning_retry_max_seconds", 61),
    ],
)
def test_settings_reject_unsafe_retry_values(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})
