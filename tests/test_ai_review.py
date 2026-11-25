"""tests/ai_review.py 的单测。

这个脚本只在 GitHub Actions 里跑，但它是「检查有没有问题」的那一道闸门，
所以它自己的重试、脱敏、跳过逻辑要有测试——闸门坏了没人知道。
"""

from __future__ import annotations

import ast
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


def test_changed_file_context_includes_source_skips_noise(ai_review, tmp_path, monkeypatch):
    """只给 diff 时模型爱写「无法确认」，所以要附上改动文件的全文。"""
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "huge.py").write_text("x = 1\n" * 5000, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    context = ai_review.changed_file_context(["mod.py", "huge.py", "missing.py", "logo.png"])

    assert "def f():" in context
    # 源码不脱敏：脱敏后的 `api_key=***` 会被模型当成语法错误去报。
    (tmp_path / "cfg.py").write_text('KEY = "OPENAI_API_KEY=abc"\n', encoding="utf-8")
    assert "OPENAI_API_KEY=abc" in ai_review.changed_file_context(["cfg.py"])
    assert "huge.py" not in context, "超长文件不截断后塞进去骗模型"
    assert "missing.py" not in context


def test_call_deepseek_does_not_retry_bad_json(ai_review, monkeypatch):
    """返回体结构不对是契约问题，重试三次也不会变好，还会掩盖真实原因。"""
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        return io.BytesIO(b"not json at all")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="JSON"):
        ai_review.call_deepseek("system", "user")
    assert calls["n"] == 1


def test_call_deepseek_retries_connection_errors(ai_review, monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        raise urllib.error.URLError("connection reset")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ai_review.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="连续 3 次"):
        ai_review.call_deepseek("system", "user")
    assert calls["n"] == 3


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


def test_empty_failure_log_exits_green_in_main(ai_review, monkeypatch, capsys):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review.sys, "argv", ["ai_review.py", "ci", "--run-id", "9"])
    monkeypatch.setattr(ai_review, "collect_ci", lambda run_id, sha: (_ for _ in ()).throw(ai_review.EmptyLog("no log")))

    assert ai_review.main() == 0
    assert "skipped" in capsys.readouterr().out


def test_empty_failure_log_is_skipped(ai_review, monkeypatch, capsys):
    def fake_run(cmd, stdin_text=None):
        return "   \n"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "stub-key")
    monkeypatch.setattr(ai_review, "run", fake_run)

    with pytest.raises(ai_review.EmptyLog):
        ai_review.collect_ci(123, "abc")


def test_upsert_patches_existing_pr_comment(ai_review, monkeypatch):
    """已有带 PR_MARKER 的旧评论：只 PATCH，不新建；返回旧评论的 html_url。"""
    existing_url = "https://github.com/zhugela/scenechoice/pull/12#issuecomment-2"
    commands: list[list[str]] = []
    patched: dict = {}

    def fake_run(cmd, stdin_text=None):
        commands.append(cmd)
        if cmd[:3] == ["gh", "api", "--paginate"]:
            return json.dumps(
                [
                    {"id": 1, "body": "旧 CI 诊断\n" + ai_review.CI_MARKER, "html_url": "https://example.test/ci"},
                    {"id": 2, "body": "旧审查\n" + ai_review.PR_MARKER, "html_url": existing_url},
                ]
            )
        if cmd[:3] == ["gh", "api", "--method"] and cmd[3] == "PATCH":
            patched.update(json.loads(Path(cmd[cmd.index("--input") + 1]).read_text(encoding="utf-8")))
            return json.dumps({"id": 2, "html_url": existing_url})
        raise AssertionError(f"未预期的命令：{cmd}")

    monkeypatch.setattr(ai_review, "run", fake_run)
    monkeypatch.setattr(ai_review, "repo_slug", lambda: "zhugela/scenechoice")

    url = ai_review.upsert("pr", "12", ai_review.PR_MARKER + " 最新审查", ai_review.PR_MARKER)

    assert url == existing_url
    methods = [cmd[3] for cmd in commands if cmd[:3] == ["gh", "api", "--method"]]
    assert methods == ["PATCH"], "已有同 marker 的评论时只改不新建"
    assert "repos/zhugela/scenechoice/issues/comments/2" in commands[-1]
    assert "最新审查" in patched["body"]
    assert ai_review.PR_MARKER in patched["body"], "PATCH 后必须保留 marker，下次才能再认出来"


def test_upsert_posts_when_no_comments(ai_review, monkeypatch):
    """目标上一条评论都没有：沿用旧的 POST 行为。"""
    new_url = "https://github.com/zhugela/scenechoice/pull/12#issuecomment-99"
    commands: list[list[str]] = []
    posted: dict = {}

    def fake_run(cmd, stdin_text=None):
        commands.append(cmd)
        if cmd[:3] == ["gh", "api", "--paginate"]:
            return "[]"
        if cmd[:3] == ["gh", "api", "--method"] and cmd[3] == "POST":
            posted.update(json.loads(Path(cmd[cmd.index("--input") + 1]).read_text(encoding="utf-8")))
            return json.dumps({"html_url": new_url})
        raise AssertionError(f"未预期的命令：{cmd}")

    monkeypatch.setattr(ai_review, "run", fake_run)
    monkeypatch.setattr(ai_review, "repo_slug", lambda: "zhugela/scenechoice")

    assert ai_review.upsert("pr", "12", ai_review.PR_MARKER + " 最新审查", ai_review.PR_MARKER) == new_url
    methods = [cmd[3] for cmd in commands if cmd[:3] == ["gh", "api", "--method"]]
    assert methods == ["POST"]
    assert ai_review.PR_MARKER in posted["body"]


def test_upsert_does_not_overwrite_ci_comment_in_pr_mode(ai_review, monkeypatch):
    """只有 CI_MARKER 的评论：PR 报告不能覆盖它，只能新建。"""
    ci_url = "https://github.com/zhugela/scenechoice/pull/12#issuecomment-3"
    new_url = "https://github.com/zhugela/scenechoice/pull/12#issuecomment-99"
    commands: list[list[str]] = []

    def fake_run(cmd, stdin_text=None):
        commands.append(cmd)
        if cmd[:3] == ["gh", "api", "--paginate"]:
            return json.dumps([{"id": 3, "body": "CI 诊断\n" + ai_review.CI_MARKER, "html_url": ci_url}])
        if cmd[:3] == ["gh", "api", "--method"] and cmd[3] == "POST":
            return json.dumps({"html_url": new_url})
        raise AssertionError(f"未预期的命令：{cmd}")

    monkeypatch.setattr(ai_review, "run", fake_run)
    monkeypatch.setattr(ai_review, "repo_slug", lambda: "zhugela/scenechoice")

    assert ai_review.upsert("pr", "12", ai_review.PR_MARKER + " 最新审查", ai_review.PR_MARKER) == new_url
    methods = [cmd[3] for cmd in commands if cmd[:3] == ["gh", "api", "--method"]]
    assert methods == ["POST"], "CI 的 marker 不是 PR 的，不许覆盖"
    assert all("comments/3" not in part for cmd in commands for part in cmd)


def test_collect_pr_flags_truncated_diff(ai_review, monkeypatch, tmp_path):
    """diff 被截断时要告诉模型边界，否则它会凭猜测说「看不到实现」。"""
    monkeypatch.setattr(ai_review, "MAX_DIFF_CHARS", 50)
    long_diff = tmp_path / "long.diff"
    long_diff.write_text("+" + "x" * 200 + "\n", encoding="utf-8")

    context = ai_review.collect_pr(0, str(long_diff))

    assert context.startswith("⚠ 本次 diff 已截断")
    assert "原始 202 字符" in context
    assert "只送入 50 字符" in context

    short_diff = tmp_path / "short.diff"
    short_diff.write_text("+x\n", encoding="utf-8")
    assert "已截断" not in ai_review.collect_pr(0, str(short_diff))


def test_upsert_adopts_the_newest_legacy_comment(ai_review, monkeypatch):
    """升级前发的报告没有 marker：认领最新那条，不许多发一条。

    历史遗留的三条重复评论就是这么产生的：报告没有身份，脚本每次只能新建。
    修好之后第一次运行应当把它接管成带 marker 的正规报告。
    """
    legacy_new = "https://example.test/legacy-new"
    commands: list[list[str]] = []
    patched: dict = {}

    def fake_run(cmd, stdin_text=None):
        commands.append(cmd)
        if cmd[:3] == ["gh", "api", "--paginate"]:
            return json.dumps(
                [
                    {
                        "id": 7,
                        "body": ai_review.LEGACY_PR_PREFIX + "\n\n旧报告一",
                        "html_url": "https://example.test/legacy-old",
                        "created_at": "2026-11-23T02:19:51Z",
                    },
                    {
                        "id": 8,
                        "body": ai_review.LEGACY_PR_PREFIX + "\n\n旧报告二",
                        "html_url": legacy_new,
                        "created_at": "2026-11-23T03:38:02Z",
                    },
                ]
            )
        if cmd[:3] == ["gh", "api", "--method"] and cmd[3] == "PATCH":
            patched.update(json.loads(Path(cmd[cmd.index("--input") + 1]).read_text(encoding="utf-8")))
            return json.dumps({"id": 8, "html_url": legacy_new})
        raise AssertionError(f"未预期的命令：{cmd}")

    monkeypatch.setattr(ai_review, "run", fake_run)
    monkeypatch.setattr(ai_review, "repo_slug", lambda: "zhugela/scenechoice")

    url = ai_review.upsert(
        "pr", "12", ai_review.PR_MARKER + " 新报告", ai_review.PR_MARKER, ai_review.LEGACY_PR_PREFIX
    )

    assert url == legacy_new
    methods = [cmd[3] for cmd in commands if cmd[:3] == ["gh", "api", "--method"]]
    assert methods == ["PATCH"], "有遗留报告时应认领，不许再新建"
    assert any("issues/comments/8" in part for part in commands[-1]), "要认领最新那条，不是最旧的"
    assert ai_review.PR_MARKER in patched["body"]


def test_upsert_rejects_body_without_marker(ai_review, monkeypatch):
    """忘带认领标记要当场炸，不许静默再贴一条。

    这是删掉“自动补 marker”之后换来的代价：调用方必须自己带。
    静默的后果是评论一条条堆起来、几天后才被发现（PR #12 就是这么变成 3 条的）。
    """
    def fake_run(cmd, stdin_text=None):
        raise AssertionError(f"不该发出任何请求：{cmd}")

    monkeypatch.setattr(ai_review, "run", fake_run)
    monkeypatch.setattr(ai_review, "repo_slug", lambda: "zhugela/scenechoice")

    with pytest.raises(ValueError, match="认领标记"):
        ai_review.upsert("pr", "12", "没有标记的正文", ai_review.PR_MARKER)


def _calls(node, name: str) -> bool:
    return any(
        isinstance(sub, ast.Call)
        and getattr(sub.func, "id", getattr(sub.func, "attr", None)) == name
        for sub in ast.walk(node)
    )


def test_upsert_calls_are_not_wrapped_in_try(ai_review):
    """写评论那一步不许被 try 包住。

    入口检查靠“抛出去”守卫：一旦有人为了“别让审查把 CI 弄红”加上
    `except Exception: pass`，忘带标记就会退回静默堆评论的老毛病。
    """
    tree = ast.parse(Path(ai_review.__file__).read_text(encoding="utf-8"))
    offenders = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Try) and _calls(node, "upsert")]
    assert offenders == [], f"upsert 被 try 包住了，行号：{offenders}"


def test_workflow_never_swallows_review_failures(ai_review):
    """工作流里不许给审查步骤加 continue-on-error。

    加了它，脚本非 0 退出也会显示绿色，等于把“不吞错”的守门关掉。
    """
    workflow = Path(ai_review.__file__).resolve().parent.parent / ".github" / "workflows" / "ai-review.yml"
    assert "continue-on-error" not in workflow.read_text(encoding="utf-8")
