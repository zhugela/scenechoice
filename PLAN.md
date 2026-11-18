# PLAN — M2 第 6 批：把「上游错误 → 应用错误」收敛成一份 + 补全 `/api/stories` 的错误矩阵

> 上一份 PLAN（M2 第 5 批：存档恢复 + endings 顺序）的两个任务已于提交 `bf59f40` / `2211b8b` 落地，并在 `sc-m2-05` 记为 passing。
> 本批来源：`docs/harness/reviews/latest.md` 的两条 P2 —— 「上游错误映射整段复制两份」与「新端点错误码矩阵只覆盖 7 种组合」。
> 本批**只做这两条**，其余 P2/P3 留下一批。

## 背景事实（别重新推理，直接按这里改）

### 现状 1：同一张映射表写了两遍，且副本丢了异常链

`app/api/story_plans.py:48-87`（preview 侧，**这份是基准**）与 `app/api/stories.py:41-87`（落库侧，**这份是副本**）逐条相同：

```python
# app/api/story_plans.py:48-60（节选）
    except DeepSeekClientError as exc:
        if exc.status_code in {401, 403}:
            raise AppError(
                "story model credentials were rejected",
                code=50302,
                status_code=503,
            ) from exc
        if exc.status_code == 402:
            raise AppError(
                "story model account has insufficient balance",
                code=50303,
                status_code=503,
            ) from exc
```

副本 `app/api/stories.py:45-49` 长这样——**没有 `from exc`**：

```python
            raise AppError(
                "story model credentials were rejected",
                code=50302,
                status_code=503,
            )
```

它是个 `NoReturn` 辅助函数（`def _raise_planning_error(exc: Exception) -> NoReturn:`，`app/api/stories.py:41`），内部 `raise` 不会自动把 `exc` 挂成 `__cause__`，所以「原始上游错误」这条线索在落库路径上断了。

**具体反例**：以后有人要支持 `425 Too Early`（确实该算可重试），改 `app/clients/deepseek.py` 的 `is_retryable_status` 两边都会跟上——这一步是对的。
但如果改的是**分支结构**（例如把 402 从 503 改成 400），他很容易只改 `story_plans.py` 一侧：
`POST /api/story-plans/preview` 返回 `400/50202`，而 `POST /api/stories` 还返回 `503/50303`。同一个上游错误，两个接口给出两种契约，而 CI 全绿——因为下面这条。

### 现状 2：测试矩阵只守住一半，改坏也不红

`tests/test_stories_api.py:401-447` 的矩阵只有 7 组：401 / 402 / 200(畸形) / 400 / 302 / None / `StoryPlanningError`。

**缺**：403、408、429、500。而 preview 侧的同一张表（`tests/test_story_plans_api.py:204-213`）是有的：

```python
        (401, 503, 50302, "story model credentials were rejected"),
        (403, 503, 50302, "story model credentials were rejected"),
        (408, 502, 50201, "story model is temporarily unavailable"),
        (429, 502, 50201, "story model is temporarily unavailable"),
        (500, 502, 50201, "story model is temporarily unavailable"),
        (422, 400, 50202, "story model rejected the request"),
```

`tests/test_retryable_status_source.py` 里那个扫 400..599 的全量循环也只打 `/api/story-plans/preview`，没打 `/api/stories`。

所以现在把 `app/api/stories.py` 里对 `is_retryable_status` 的判断去掉、让 408/429 落进 `400/50202`，**没有任何测试会红**。

## 要修的两条

### ① [P2] 映射收敛成一份函数，两个路由都调它

- 新增一个共享函数，签名建议 `def provider_error_to_app_error(exc: DeepSeekClientError) -> AppError`；位置你自己定（`app/clients/deepseek.py` 或 `app/services/` 下的新模块），但必须在报告里说清为什么放那里——判断依据是「这份知识归哪一层」，不是「哪里好 import」。
- `app/api/story_plans.py` 与 `app/api/stories.py` 都改成调用它；两个路由里不再出现 `50302/50303/50201/50202/50204` 这些字面量。
- **异常链不许丢**：调用方一律 `raise app_error from exc`。这是本批唯一「修好一处真实缺陷」的点，别当顺手。
- `StoryPlanningError → 422/42201` 不是「上游 HTTP 错误」，**不要**塞进同一个函数，保持各自路由处理（两个路由现在的行为本来就一致）。

### ② [P2] 把矩阵补齐，并加一条「只改一处会变红」的一致性网

- `tests/test_stories_api.py:401-447` 的表补上 **403 / 408 / 429 / 500** 四组，期望值照 preview 表抄（那是已定契约）。
- 把 `tests/test_retryable_status_source.py` 里 400..599 的全量循环**扩到 `/api/stories`**：同一组状态码，两个端点返回的 `(status_code, code, message)` 三元组必须完全相同。这条才是真正守住「两份不会漂移」的网。
  - 若 508 个状态 × 两个端点跑起来太慢（单条 >5s），可以抽成两边共用同一张参数表各自参数化，但**不许**只测其中一个端点。
- 报告里给出这条一致性测试的单跑耗时，供我决定它留在默认套件还是打 `slow` 标记。

## 不许做的事

- 不许改 M1 `preview` 的**对外行为**：401/403/402/200 畸形/永久 4xx/1xx-3xx/5xx 的既有映射一个都不许变（`tests/test_story_plans_api.py:204-232` 全绿是硬约束）。
- 不许放宽或删除任何已有断言的预期值；只允许**新增**用例、把已有表**扩行**。
- 不许顺手改本批之外的 P2/P3（`blueprint_version` 校验、savepoint 测试、secret 泄漏、WAL、幂等键都留给下一批）。
- 不许改 `app/services/blueprint_validator.py`、`app/schemas/story_blueprint.py`、`alembic/versions/` 下任何文件。
- 不许 `git add` / `git commit` / `git push`（提交由本人决定）。
- 不许为了「让测试过」去改对外行为——本批是**重构 + 补测试**，对外行为零变化。

## 验收底线（缺一条就不算做完）

1. **基线**：动手前先跑一次 `.venv/Scripts/python.exe -m pytest -q`，把真实数字写进报告（当前应为 `153 passed`）。
2. **红绿证据（本批核心，必须真跑）**——用变异测试证明「改坏一处会变红」，不是嘴上说：
   - 先让收敛后的实现跑绿；
   - 然后**临时**把共享函数里的可重试判断改坏一处（例如把 `is_retryable_status(x)` 换成 `False`），跑测试，**必须至少 `1 failed`**，把失败用例名与断言贴出来；
   - 再改回来，跑全绿；
   - 报告里写清「改了哪一行 → 哪个用例红了 → 恢复后绿」，并用 `git diff` 自证那一行**没留在最终代码里**。
3. **异常链**：补一条测试断言落库路径上 `AppError.__cause__` 是原始 `DeepSeekClientError`（preview 侧若已有类似写法就照抄，没有就新增）。这是本批唯一能证明「副本曾丢 chain」的回归网。
4. **映射只剩一份**：`grep -rn "50302\|50303\|50201\|50202\|50204" app/` 的结果里，这些字面量只应出现在**一个**模块（共享函数所在处），`app/api/*.py` 里一个都不该有。把 grep 输出贴进报告。
5. **全量**：`.venv/Scripts/python.exe -m pytest -q` 全绿，且总数 > 153。贴真实输出末行。
6. **不动 M1**：`git diff --stat` 里 M1 相关文件只应出现 `app/api/story_plans.py`（因收敛而被改，允许），其余 M1 文件零改动。

## 收工要输出什么

1. 改了哪几个文件、每处为什么这么改（一张表：文件 / 改了什么 / 为什么）。
2. 上面六条验收的**真实命令输出**，尤其是第 2 条的变异红绿三段与第 4 条的 grep。
3. 仍然存在的风险（例如一致性测试变慢、`_raise_planning_error` 删没删、499/409 语义未动）。
4. `docs/harness/progress.md` 与 `PLAN.md` 不算你的改动——那两份由本人（Hermes）来写。
