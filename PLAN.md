# PLAN

目标：修复巡检报告 P2-2 —— DeepSeek 返回的永久 4xx（400/404/422）被错误地映射成「模型临时不可用 502」，导致调用方白白重试。

## 错误码方案（已定，按此实现）

| DeepSeek 返回 | 现在 | 改成 | 理由 |
|---|---|---|---|
| 401 / 403 | 503 / 50302 | **不变** | 凭证被拒，需要人换 key |
| 408 / 429 | 502 / 50201 | **不变** | 真的是临时限流/超时，重试有意义 |
| 5xx | 502 / 50201 | **不变** | 上游故障，可重试 |
| **400 / 404 / 422 / 其他 4xx** | 502 / 50201 | **400 / 50202** | 请求本身错了，重试一万次也一样 |

错误文案改为「story model rejected the request」（不再说 temporarily unavailable）。

## 约束

1. 不许改 `tests/` 里已有用例的预期结果，只允许新增。
2. 不许为了让测试变绿放宽判定。
3. 每处改动必须配测试。
4. 收工前 `.venv/Scripts/python.exe -m pytest -q` 必须全绿（当前基线 **102 passed**）。
5. 不许 `git add` / `git commit` / `git push`。
6. 只动 `app/clients/deepseek.py`、`app/api/story_plans.py` 和对应测试。

## 背景事实（已核实，不要重新推测）

- `app/clients/deepseek.py:90-98`：
  ```python
  retryable = status_code in {408, 429} or status_code >= 500
  ```
  4xx（非 408/429）时 retryable=False，立即抛 `StoryModelError`。
- `app/api/story_plans.py:36-43`：
  ```python
  if exc.status_code in {401, 403}:
      raise AppError("story model credentials were rejected", code=50302, status_code=503)
  raise AppError("story model is temporarily unavailable", code=50201, status_code=502)
  ```
  没有分支处理 400/404/422，全部落到 502。
- 现有测试只覆盖 401→50302（`tests/test_story_plans_api.py:82-94`）与 `StoryPlanningError`→42201（`:97-108`），**50200/50202 分支没有任何运行时测试**。

## 子任务队列

- [ ] 基线确认：`.venv/Scripts/python.exe -m pytest -q`，记录 passed 数量
- [ ] 复现缺陷：写一条测试，让 FakeClient 返回 400，断言当前 API 返回 **502/50201**，先让它红着当证据
- [ ] 改 `app/api/story_plans.py`：加 4xx（排除 401/403/408/429）分支 → `status_code=400, code=50202`
- [ ] 把复现测试改成断言 **400/50202**（变绿）
- [ ] 补测试：401→50302（确认没被改坏）、403→50302、408→50201、429→50201、500→50201、422→400/50202
- [ ] 确认 `deepseek.py` 的 retryable 判定不需要动（4xx 本来就不重试）；如需要请说明理由
- [ ] 跑全量测试，结果写进 `docs/harness/progress.md`（新开 Session 005 段落）
- [ ] 输出改动摘要：改了哪几处、错误码最终怎么定的、新增几条测试

## 不要做的事

- 不要动规则 10（P2-3，需要产品决策，下一轮）
- 不要碰 `blueprint_validator.py`（规则4/规则9 已修完，别回改）
- 不要重构 AppError 或统一异常处理的结构
