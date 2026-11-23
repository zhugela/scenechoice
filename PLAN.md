# PLAN — 工具批：AI 审查评论去重（同一个 PR 只维护一条报告）

> 来源：负责人转来的分析（PR #12 上 3 条重复的 AI 审查评论）+ Hermes 自己核实：
> `gh api repos/zhugela/scenechoice/issues/12/comments` 上确实有 3 条 `github-actions[bot]`
> 评论（2026-11-23T02:19 / 03:16 / 03:38Z），全部是 `scripts/ai_review.py` 用 **POST 新建**的。
> 基线：`498886a`，`240 passed`。

## 一、问题（已核实）

| 事实 | 证据 |
|---|---|
| 每次 push 到 PR 分支都会重新审查 | `.github/workflows/ai-review.yml` 的 `pull_request: types: [opened, synchronize, reopened, ready_for_review]` —— **保留**这个触发，不是 bug |
| 每次都新建评论，越积越多 | `scripts/ai_review.py` 的 `post()` 只有 POST 分支；PR #12 上 3 条评论可查 |
| diff 过长会被截断，模型还会抱怨"看不到实现" | `MAX_DIFF_CHARS = 60_000`、`MAX_FILE_CHARS = 8_000`、`MAX_CONTEXT_CHARS`，截断时**没有告诉模型，也没有写进报告** |

## 二、本批做什么（三件）

### U1 一条评论 upsert（主功能）

- 新增模块常量：`PR_MARKER = "<!-- ai-review:pr -->"`、`CI_MARKER = "<!-- ai-review:ci -->"`。
- 新增 `upsert(kind: str, target: str, body: str, marker: str) -> str`：
  1. 列出目标上已有评论：
     - `pr` → `gh api --paginate "repos/{slug}/issues/{target}/comments"`
     - `commit` → `gh api --paginate "repos/{slug}/commits/{target}/comments"`
  2. 找**正文里含 `marker`** 的第一条：
     - 找到 → `PATCH repos/{slug}/issues/comments/{id}`（commit 用 `repos/{slug}/comments/{id}`）→ 返回它的 `html_url`
     - 找不到 → 走现在的 POST
  3. 只认 marker，不认作者名（fork PR 里 bot 名字可能带前缀）；marker 不同的（PR vs CI 诊断）不许互相覆盖。
- `main()` 里 PR 模式改用 `upsert(..., PR_MARKER)`；CI 模式改用 `upsert(..., CI_MARKER)`。
- 正文加一行更新戳：`> 最近更新：<sha 前 7 位> · <UTC ISO 时间>`，让读者一眼知道这是同一份报告的最新版。

### U2 截断要说人话

- `collect_pr()` 组装 context 时，若 diff 长度 > `MAX_DIFF_CHARS`，在 context **顶部**加一行：
  `⚠ 本次 diff 已截断：原始 N 字符，只送入 M 字符；未送入的部分没有参与审查。`
- 目的：模型不再凭猜测说"看不到实现"，人也知道这次审查的边界。

### U3 测试（4 条，`tests/test_ai_review.py` 追加）

| # | 用例 | 断言 |
|---|---|---|
| 1 | 已有带 `PR_MARKER` 的旧评论 | 只发 **PATCH**，不发 POST；返回旧评论的 `html_url` |
| 2 | 没有任何评论 | 发 POST（沿用旧行为） |
| 3 | 只有带 `CI_MARKER` 的评论，本次是 PR 模式 | 不许覆盖它，走 POST |
| 4 | 超长 diff | context 含「已截断」；未超长时不含 |

## 三、禁改清单

- `.github/workflows/ai-review.yml` 的触发类型（`synchronize` 必须留：最新提交就该被审）
- `PR_SYSTEM` / `CI_SYSTEM` 提示词
- 任何已有测试的预期结果
- `app/` 下所有代码

## 四、验收标准

1. `pytest -q` ≥ 244；已有用例零改动。
2. 变异 A：删掉 `upsert` 的 PATCH 分支（永远走 POST）→ 用例 1 变红。
3. 变异 B：marker 判断改成恒 `False` → 用例 1 变红。
4. 变异 C：去掉截断提示 → 用例 4 变红。
5. 真实跑一次 `AI_REVIEW_STUB=1 python scripts/ai_review.py pr --number 12 --dry-run` 不报错（不真的发评论）。
