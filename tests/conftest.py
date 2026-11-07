import socket

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep offline tests independent from local config and real networks."""
    for name in (
        "SCENECHOICE_APP_NAME",
        "SCENECHOICE_APP_ENV",
        "SCENECHOICE_DEBUG",
        "SCENECHOICE_DEEPSEEK_API_KEY",
        "SCENECHOICE_DEEPSEEK_BASE_URL",
        "SCENECHOICE_DEEPSEEK_MODEL",
        "SCENECHOICE_DEEPSEEK_TIMEOUT_SECONDS",
        "SCENECHOICE_DEEPSEEK_MAX_TOKENS",
        "SCENECHOICE_STORY_PLANNING_MAX_ATTEMPTS",
        "SCENECHOICE_STORY_PLANNING_RETRY_BASE_SECONDS",
        "SCENECHOICE_STORY_PLANNING_RETRY_MAX_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    # Settings loads `.env` relative to cwd. A clean temp cwd prevents a
    # developer's local key from changing test behavior.
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    original_connect = socket.socket.connect

    def block_real_network(sock, address):
        host = address[0] if isinstance(address, tuple) and address else None
        if host in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError(f"offline test attempted a real network connection to {host}")

    monkeypatch.setattr(socket.socket, "connect", block_real_network)
    yield
    get_settings.cache_clear()
