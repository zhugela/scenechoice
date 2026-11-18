"""tests/ai_review.py 的单测。

这个脚本只在 GitHub Actions 里跑，但它是「检查有没有问题」的那一道闸门，
所以它自己的重试、脱敏、跳过逻辑要有测试——闸门坏了没人知道。
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ai_review.py"


@pytest.fixture(scope="module")
def ai_review():
    spec = importlib.util.spec_from_file_location("ai_review_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _http_error(code: int) -> urllib.error.HTTPError:
    # hdrs 传 None：这里只关心状态码，构造一个真实响应头没有意义。
    return urllib.error.HTTPError("https://example.test", code, "boom", None, io.BytesIO(b'{"error":"x"}'))  # type: ignore[arg-type]


def _ok_body(text: str) -> io.BytesIO:
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}}]}).encode())


def test_redact_masks_common_secret_shapes(ai_review):
    raw = "api_key=sk-abcdefghijklmnopqrst\nAuthorization: ghp_0123456789abcdefghij\nOPENAI_API_KEY=plainvalue"
    cleaned = ai_review.redact(raw)
    assert "sk-abcdefghijklmnopqrst" not in cleaned
    assert "ghp_0123456789abcdefghij" not in cleaned
    assert "plainvalue" not in cleaned
    assert cleaned.count("REDACTED") == 3


def test_call_deepseek_retries_server_errors(ai_review, monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(503)
        return io.BytesIO(_ok_body("审查结果").read())

    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ai_review.time, "sleep", lambda _s: None)

    assert ai_review.call_deepseek("system", "user") == "审查结果"
    assert calls["n"] == 3


def test_call_deepseek_gives_up_after_three_server_errors(ai_review, monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        raise _http_error(500)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ai_review.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="连续 3 次"):
        ai_review.call_deepseek("system", "user")
    assert calls["n"] == 3


def test_call_deepseek_does_not_retry_client_errors(ai_review, monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        raise _http_error(401)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="401"):
        ai_review.call_deepseek("system", "user")
    assert calls["n"] == 1, "4xx 是配置错误，重试只会浪费时间和额度"


def test_stub_mode_runs_without_api_key(ai_review, monkeypatch, tmp_path, capsys):
    diff = tmp_path / "sample.diff"
    diff.write_text("diff --git a/x.py b/x.py\n+x = 1\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("AI_REVIEW_STUB", "1")
    monkeypatch.setattr(ai_review.sys, "argv", ["ai_review.py", "pr", "--diff-file", str(diff), "--dry-run"])

    assert ai_review.main() == 0
    assert "STUB" in capsys.readouterr().out


def test_pr_mode_without_key_skips_green(ai_review, monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("AI_REVIEW_STUB", raising=False)
    monkeypatch.setattr(ai_review.sys, "argv", ["ai_review.py", "pr", "--number", "1"])

    assert ai_review.main() == 0
    assert "skipped" in capsys.readouterr().out


def test_diff_file_requires_dry_run(ai_review, monkeypatch, tmp_path):
    diff = tmp_path / "sample.diff"
    diff.write_text("diff --git a/x.py b/x.py\n+x = 1\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review.sys, "argv", ["ai_review.py", "pr", "--diff-file", str(diff)])

    with pytest.raises(SystemExit):
        ai_review.main()


def test_empty_failure_log_is_skipped(ai_review, monkeypatch, capsys):
    def fake_run(cmd, stdin_text=None):
        return "   \n"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review, "run", fake_run)

    with pytest.raises(ai_review.EmptyLog):
        ai_review.collect_ci(123, "abc")
