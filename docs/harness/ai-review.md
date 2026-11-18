# 自动审查（AI Review）

push 完不用自己盯 CI 结果：仓库里两个工作流会把"有没有问题、问题在哪、怎么改"贴回 GitHub。

| 工作流 | 什么时候跑 | 干什么 |
|---|---|---|
| `ci.yml` | push 到 master/main、任何 PR、手动 | 跑 `pytest -q`（原有，129+ 个测试） |
| `ai-review.yml` → 审查 PR 改动 | PR 打开、更新、重新打开 | 把整个 `git diff` 交给 DeepSeek，按项目硬规则挑问题，评论在该 PR 上 |
| `ai-review.yml` → 诊断 CI 失败 | `ci.yml` 跑挂之后 | 把失败日志（含 traceback）交给 DeepSeek，说清根因 + 最小修复步骤，评论在 PR 或那个提交上 |

脚本是 `scripts/ai_review.py`，只用标准库，Actions 里不装任何依赖。

## 一次性配置

只有一件事要人做：把 key 存进仓库 secret。

```bash
gh secret set DEEPSEEK_API_KEY          # 交互粘贴，不落盘、不进 shell 历史
```

可选（默认值够用）：

```bash
gh variable set DEEPSEEK_BASE_URL --body "https://api.deepseek.com"
gh variable set DEEPSEEK_MODEL    --body "deepseek-chat"
```

没配 secret 时，AI 步骤打印 `skipped` 并退出 0，工作流保持绿，不会拦住合并。

## 审查按什么规则挑问题

`scripts/ai_review.py` 里的 system prompt 写死了这个项目的硬规则，不是泛泛的"代码看起来不错"：

- 三层分离：`app/api` 只收参数、`app/services` 业务、`app/clients` 才发 HTTP。
- 双层校验：Pydantic 管形状，service 层 validator 管语义；只加 Pydantic 算缺陷。
- 模型调用最多重试 3 次；错误要翻译成人话再喂回模型。
- 测试默认不联网；新增外部调用必须有 mock 的失败路径。
- 改 ORM 必须配 Alembic 迁移，反之亦然。

评论固定四个小节：结论 / 阻塞问题 / 非阻塞建议 / 缺失的测试。

定位按 `path:函数名`。只给 diff 时模型没法看上下文，会退化成一堆「无法确认」；所以脚本会把
**改动文件的完整内容**（`.py`/`.yml` 等，单文件 <8k、合计 <40k 字符）一起送过去。超长文件直接跳过，
不拿截断的半个文件骗它。

## 故意不做的事

- **不自动改代码、不自动合并。** 让 agent 自己改自己审等于没人把关；审查结论仍然是给人读的。
- **不放宽 `ci.yml`。** AI 是加法，不是给红测试找理由的。
- 不动 `feature_list.json` 的状态；`passing` 仍然要有真实证据。

## 成本

每次 PR 更新一次调用：最多 6 万字符 diff，加最多 4 万字符文件全文。切到 `synchronize` 事件意味着每 push 一次就调一次；想省钱就把 workflow 里的 `synchronize` 去掉，只在开 PR 时审一次。

## 本地试跑

```bash
export DEEPSEEK_API_KEY=...            # 或 AI_REVIEW_STUB=1 走假数据验证管道
python scripts/ai_review.py pr --number 12 --dry-run
python scripts/ai_review.py ci --run-id 123456 --dry-run
```

`--dry-run` 只打印不评论。
