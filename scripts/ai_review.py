#!/usr/bin/env python3
"""把 PR diff 或 CI 失败日志交给 DeepSeek，产出可直接执行的审查结论。

只用标准库，所以 CI 里不需要装任何依赖。

用法
----
    python scripts/ai_review.py pr  --number 12
    python scripts/ai_review.py pr  --diff-file /tmp/x.diff   # 本地试跑
    python scripts/ai_review.py ci  --run-id 123 [--sha abc]
    python scripts/ai_review.py pr  --number 12 --dry-run     # 只打印不发评论

环境变量
--------
    DEEPSEEK_API_KEY    必需；缺失时打印 skipped 并退出 0（workflow 保持绿）
    DEEPSEEK_MODEL      默认 deepseek-chat
    DEEPSEEK_BASE_URL   默认 https://api.deepseek.com
    GH_TOKEN            由 Actions 注入；本地用已登录的 gh
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

MAX_DIFF_CHARS = 60_000
MAX_LOG_CHARS = 40_000


class EmptyLog(RuntimeError):
    """失败日志为空：没什么可喂给模型的，跳过比瞎猜好。"""

# 送进第三方模型之前先抹掉长得像密钥的东西：仓库是公开的，日志里也可能带 key。
SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***REDACTED***"),
    (re.compile(r"(?i)([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*[=:]\s*)\S+"), r"\1***REDACTED***"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "gh*_***REDACTED***"),
]

PR_SYSTEM = """你是一个严格的高级工程师，在给一个 Python/FastAPI AI 项目做代码审查。

只报告你能在 diff 里指出来的具体问题。禁止写「代码风格可以更好」「建议增加注释」这类空话，
禁止夸奖。找不到问题就直说没有阻塞问题。

定位写法：你看到的 diff 只有 hunk 头（`@@ -12,7 +12,9 @@`）能定位行号。引用位置统一写成
`path:函数名` 或 `path:@@ 后的新行号起止`，例如 `scripts/ai_review.py:call_deepseek`。
**不许猜行号**，写出 `:1` 这种没有依据的行号等于没说清位置。

不要评论第三方库、GitHub Action、SDK 的版本号新旧——你没有最新的版本信息，猜错会误导人。
只有 diff 里明确出现版本冲突时才提。

某条判断你没有把握时，直接写「不确定」，不要为了凑数编一条。

这个项目的硬规则（违反要报出来）：
- 三层分离：app/api 只收参数调用 service；app/services 业务逻辑；app/clients 才发 HTTP。
  api 层出现 httpx/requests 调用、或 service 直接读 FastAPI Request，都算越界。
- 双层校验：Pydantic 管形状，service 层业务 validator 管语义（跨字段、业务可执行性）。
  只加 Pydantic 校验就算通过，是缺陷。
- 对外部模型调用最多重试 3 次；错误要翻译成人话再喂回模型，不能直接把 traceback 丢给模型。
- 测试默认不联网（conftest 断网）；新增外部调用必须有 mock 的失败路径测试。
- 数据模型改动必须配套 Alembic 迁移；只改 ORM 不改迁移，或只改迁移不改 ORM，都要报。

输出严格用这个 markdown 结构，不要加别的标题：

## 结论
一句话：可以合 / 有阻塞问题 / 建议改动后再合。

## 阻塞问题
- `path:函数名` — 问题是什么 — 为什么是问题 — 建议怎么改

## 非阻塞建议
- `path:函数名` — 问题 — 建议

## 缺失的测试
- 具体要补哪个测试（名字给出），断言什么

没有内容的小节写「无」。"""

CI_SYSTEM = """你是一个值班的高级工程师。CI 在 master 或 PR 上跑挂了，你要根据失败日志给出根因和最小修复路径。

规则：
- 只依据日志里出现的证据说话，指出是哪一行、哪个测试、哪条 traceback。
- 如果日志不够定位，直说「日志不足，需要 X」，不要编造原因。
- 修复步骤要具体到文件和函数，最多 3 步。
- 不要输出大段完整代码，给关键改动就行。

输出严格用这个 markdown 结构：

## 根因
一句话。

## 证据
- 引用日志里最关键的 1-3 行

## 最小修复步骤
1. `path` — 改什么

## 需要人判断的地方
没有就写「无」。"""


def run(cmd: list[str], stdin_text: str | None = None) -> str:
    """跑一条命令，失败时把 stderr 带进异常，避免 CI 里只看到 'exit 1'。

    Windows 上 CreateProcess 找不到不带扩展名的 `gh`，先解析成绝对路径。
    """
    executable = shutil.which(cmd[0]) or cmd[0]
    proc = subprocess.run(
        [executable, *cmd[1:]], capture_output=True, text=True, encoding="utf-8", input=stdin_text, timeout=300
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} -> exit {proc.returncode}\n{proc.stderr.strip()}")
    return proc.stdout


def gh_json(args: list[str]) -> dict:
    return json.loads(run(["gh", *args]))


def redact(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def clip(text: str, limit: int, label: str) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-(limit // 2) :]
    return f"{head}\n\n... [{label}: 中间省略 {len(text) - limit} 字符] ...\n\n{tail}"


def repo_slug() -> str:
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug:
        return slug
    return gh_json(["repo", "view", "--json", "nameWithOwner"])["nameWithOwner"]


SOURCE_SUFFIXES = {".py", ".yml", ".yaml", ".toml", ".cfg", ".ini"}
MAX_FILE_CHARS = 8_000
MAX_CONTEXT_CHARS = 40_000


def changed_file_context(paths: list[str], root: Path | None = None) -> str:
    """把改动文件的完整内容附在 diff 后面。

    只给 diff 时模型经常写「无法从 hunk 确认」，把推测当结论；把全文给它，
    才能真的指出「这个函数在文件里还有另一个调用点」这类问题。
    文件太大或不存在就跳过，不拿截断的半个文件骗它。
    """
    root = root or Path.cwd()
    chunks: list[str] = []
    total = 0
    for raw_path in paths:
        path = root / raw_path
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if len(text) > MAX_FILE_CHARS or total + len(text) > MAX_CONTEXT_CHARS:
            continue
        total += len(text)
        chunks.append(f"### {raw_path}\n```\n{redact(text)}\n```")
    if not chunks:
        return ""
    return "\n\n## 改动文件当前完整内容（用来核对上下文，不要要求更多文件）\n\n" + "\n\n".join(chunks)


def collect_pr(number: int, diff_file: str | None) -> str:
    context = ""
    if diff_file:
        diff = Path(diff_file).read_text(encoding="utf-8", errors="replace")
        meta = f"(本地 diff 文件：{diff_file})"
    else:
        meta_d = gh_json(["pr", "view", str(number), "--json", "title,body,files"])
        diff = run(["gh", "pr", "diff", str(number)])
        paths = [f["path"] for f in meta_d["files"]]
        files = ", ".join(paths[:40])
        meta = redact(f"标题：{meta_d['title']}\nPR 描述：{meta_d['body'] or '(空)'}\n改动文件：{files}")
        context = changed_file_context(paths)
    return f"{meta}\n\n```diff\n{clip(redact(diff), MAX_DIFF_CHARS, 'diff')}\n```{context}"


def collect_ci(run_id: int, sha: str | None) -> tuple[str, str | None]:
    log = run(["gh", "run", "view", str(run_id), "--log-failed"])
    if not log.strip():
        raise EmptyLog(f"run {run_id} 没有可读的失败日志（可能挂在 setup 阶段），跳过诊断")
    run_info = gh_json(["api", f"repos/{repo_slug()}/actions/runs/{run_id}"])
    sha = sha or run_info["head_sha"]
    pr_number = None
    if run_info.get("pull_requests"):
        pr_number = str(run_info["pull_requests"][0]["number"])
    context = (
        f"工作流：{run_info['name']}\n提交：{sha}\n标题：{run_info['display_title']}\n"
        f"结论：{run_info['conclusion']}\n\n```\n{clip(redact(log), MAX_LOG_CHARS, '日志')}\n```"
    )
    return context, pr_number


def call_deepseek(system: str, user: str) -> str:
    # 本地验证管道用：AI_REVIEW_STUB=1 时不花钱、不联网，返回固定结构。
    if os.environ.get("AI_REVIEW_STUB") == "1":
        return f"## 结论\nSTUB（输入 {len(user)} 字符，system {len(system)} 字符）\n\n## 阻塞问题\n- 无\n\n## 非阻塞建议\n- 无\n\n## 缺失的测试\n- 无"
    key = os.environ["DEEPSEEK_API_KEY"]
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    payload = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 3000,
        "stream": False,
    }
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        request = urllib.request.Request(
            f"{base}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            if exc.code == 429 or exc.code >= 500:
                last_error = RuntimeError(f"模型服务暂时不可用（HTTP {exc.code}）：{detail}")
                print(f"attempt {attempt}: 服务端 {exc.code}，退避后重试", file=sys.stderr)
                time.sleep(attempt * 2)
                continue
            # 401/400 这类重试没意义，直接把原文给人看，别吞掉。
            raise RuntimeError(f"模型接口拒绝请求（HTTP {exc.code}）：{detail}") from exc
        except Exception as exc:  # noqa: BLE001 - 超时/连接中断属于抖动，可重试
            last_error = RuntimeError(f"连接模型服务失败：{type(exc).__name__}")
            print(f"attempt {attempt}: {type(exc).__name__}，退避后重试", file=sys.stderr)
            time.sleep(attempt * 2)
            continue

        # 响应体解析放在重试之外：返回结构不对是接口契约问题，重试三次也不会变好，
        # 把它当成「网络抖动」只会掩盖真实原因。
        try:
            data = json.loads(raw.decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"模型返回的内容不是预期的 JSON 结构：{raw[:300]!r}") from exc

    raise RuntimeError(f"连续 3 次调用模型都失败：{last_error}。检查网络出口，或稍后重跑。")



def post(kind: str, target: str, body: str) -> str:
    """评论走 --input 传 JSON，绕开 shell 引号转义（正文里有反引号和中文）。"""
    slug = repo_slug()
    if kind == "pr":
        url = f"repos/{slug}/issues/{target}/comments"
    else:
        url = f"repos/{slug}/commits/{target}/comments"
    with tempfile.TemporaryDirectory() as tmp:
        payload = Path(tmp) / "comment.json"
        payload.write_text(json.dumps({"body": body}), encoding="utf-8")
        out = run(["gh", "api", "--method", "POST", url, "--input", str(payload)])
    return json.loads(out)["html_url"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    pr_cmd = sub.add_parser("pr", help="审查一个 PR 的 diff")
    pr_cmd.add_argument("--number", type=int)
    pr_cmd.add_argument("--diff-file", help="本地试跑：直接读一个 diff 文件")
    pr_cmd.add_argument("--dry-run", action="store_true")

    ci_cmd = sub.add_parser("ci", help="诊断一次失败的 workflow run")
    ci_cmd.add_argument("--run-id", type=int, required=True)
    ci_cmd.add_argument("--sha")
    ci_cmd.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    stub = os.environ.get("AI_REVIEW_STUB") == "1"
    if not os.environ.get("DEEPSEEK_API_KEY") and not stub:
        print("skipped: 没有 DEEPSEEK_API_KEY，AI 步骤跳过，workflow 保持绿。")
        return 0

    if args.mode == "pr":
        if not args.number and not args.diff_file:
            parser.error("pr 模式需要 --number 或 --diff-file")
        if args.diff_file and not args.dry_run:
            parser.error("--diff-file 是本地试跑，必须加 --dry-run（否则会往 issues/0 发评论）")
        context = collect_pr(args.number or 0, args.diff_file)
        header = "## AI 审查（DeepSeek）\n\n"
        review = call_deepseek(PR_SYSTEM, f"这是本次 PR 的全部改动：\n\n{context}")
        body = header + review + "\n\n---\n> 由 `scripts/ai_review.py` 自动生成，仅供参考，合并前请人工判断。"
        if args.dry_run:
            print(body)
            return 0
        print("comment:", post("pr", str(args.number), body))
        return 0

    try:
        context, pr_number = collect_ci(args.run_id, args.sha)
    except EmptyLog as exc:
        print(f"skipped: {exc}")
        return 0
    diagnosis = call_deepseek(CI_SYSTEM, f"这次 CI 失败了：\n\n{context}")
    body = f"## CI 失败诊断（DeepSeek）\n\n{diagnosis}\n\n---\n> 由 `scripts/ai_review.py` 自动生成，仅供参考。"
    if args.dry_run:
        print(body)
        return 0
    if pr_number:
        print("comment:", post("pr", pr_number, body))
    else:
        slug = repo_slug()
        sha = args.sha or gh_json(["run", "view", str(args.run_id), "--json", "headSha"])["headSha"]
        print("comment:", post("commit", sha, body))
    return 0


if __name__ == "__main__":
    sys.exit(main())
