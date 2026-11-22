# PLAN — M2 第 14 批：POST 幂等键（方案 A）

> 负责人 2026-11-22 选 A：接受 `Idempotency-Key` 头，存表，重复请求回放首次响应。
> 目的不是"接口好看"，是**别把同一次生成重复扣两次 token、留两份存档**。
> 基线：`f2a386b`，`210 passed`。

## 一、现状事实

| 事实 | 证据 |
|---|---|
| `POST /api/stories` 每次都会真调一次模型并新建一份存档 | `app/api/stories.py:76-100`；`progress.md` Session 009 已记录「POST 是生成接口，超时重试会留两份存档」 |
| 没有任何幂等机制 | `grep -rn "Idempotency" app/` 零命中 |
| 迁移最新版本 | `alembic/versions/20261116_0002_add_ending_position.py`；本批要加第三个迁移 |

## 二、数据模型（新增一张表）

`app/models/idempotency.py` → `IdempotencyRecord`，表名 `idempotency_records`：

| 列 | 类型 | 约束 | 用途 |
|---|---|---|---|
| `id` | Integer PK | | 内部主键 |
| `scope` | String(64) | 非空 | 哪个端点用的 key（`stories.create`），避免不同端点共用同一个 key 撞车 |
| `key` | String(120) | 非空 | 客户端传来的 `Idempotency-Key` |
| `fingerprint` | String(64) | 非空 | 请求体的 sha256，用来识别「同一个 key 换了内容」 |
| `state` | String(20) | CHECK in (`pending`,`completed`) | 进行中 / 已完成 |
| `status_code` | SmallInteger | 可空 | 完成时记下的原始状态码 |
| `response_body` | JSON | 可空 | 完成时记下的原始响应体，用于回放 |
| `created_at` / `updated_at` | DateTime | 非空 | `updated_at` 用于判「卡住的 pending 是否过期」 |

唯一约束：`(scope, key)`。迁移文件 `alembic/versions/<日期>_0003_add_idempotency_records.py`。

## 三、服务层 `app/services/idempotency.py`

- `request_fingerprint(payload: dict) -> str`：`json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` 的 sha256。**必须规范化**，否则键顺序不同就误判成"换了内容"。
- `claim(session, *, scope: str, key: str, fingerprint: str, now=None) -> Claim`：
  - 无记录 → 插入 `state=pending`，返回 `Claim(outcome="claimed", record=...)`
  - 有记录且 `fingerprint` 不同 → `outcome="mismatch"`
  - 有记录、`completed` → `outcome="replay"`，带上 `status_code` / `response_body`
  - 有记录、`pending` 且 `updated_at` 在 **10 分钟**内 → `outcome="in_progress"`
  - 有记录、`pending` 且已超过 10 分钟（上次跑崩了）→ 覆盖成新的 `pending`（重置 fingerprint/时间），`outcome="claimed"`
  - 并发撞唯一约束（`IntegrityError`）→ 回滚该次插入后按上面规则重新读一次再判
- `complete(session, record, *, status_code: int, body: dict) -> None`：写 `completed` + 状态码 + 响应体
- `release(session, record) -> None`：删除记录（生成失败时用，让客户端能重试）

## 四、路由接线（`app/api/stories.py` 的 `create_story`）

1. 读 `Idempotency-Key` 头（可选，`strip()` 后为空视为没传；长度 >120 → 422，沿用 FastAPI 的校验错误风格或显式 AppError，你定但要写测试）。
2. 没传 → 完全走现有逻辑，行为零变化。
3. 传了 →
   - `mismatch` → `409` + `40903`（同一个 key 换了请求内容）
   - `in_progress` → `409` + `40904`（同一个请求还在处理）
   - `replay` → 直接返回存下来的 `status_code` + `response_body`，并加响应头 `Idempotent-Replay: true`
   - `claimed` → 继续生成；成功后 `complete()` 再返回；**失败路径必须 `release()`**（否则这个 key 会被卡 10 分钟）
4. `app/errors.py` 增加 `IDEMPOTENCY_KEY_REUSED = 40903`、`IDEMPOTENCY_IN_PROGRESS = 40904`，路由不许再写字面量。

## 五、测试（≥6 条，只追加）

1. 同一个 key 连续两次 → 两次返回同一个 `public_id`，库里只有 **1** 份故事；第二次带 `Idempotent-Replay: true`。
2. 同一个 key + 不同 `inspiration` → `409` + `40903`，且第二次没有新建故事。
3. 手工塞一条 `pending` 且 `updated_at` 在 1 分钟内的记录 → `409` + `40904`。
4. 手工塞一条 `pending` 且 `updated_at` 在 20 分钟前的记录 → 允许重新生成（200/201），并且记录被重置。
5. 不传 key 连续两次 → 两份不同 `public_id` 的故事（证明旧行为没变）。
6. 生成失败（planner 抛错）时记录被释放：失败后同一个 key 再请求能成功。
7. 迁移测试：`alembic upgrade head` 后 `idempotency_records` 表存在且 `(scope, key)` 唯一。

## 六、禁改清单

- 任何已有测试的预期结果
- `app/schemas/story_blueprint.py`、`app/services/{blueprint_validator,conditions,play_engine,story_planner}.py`
- 已发布的迁移 `20261115_0001` / `20261116_0002`（只许新增第三个）
- 现有端点的状态码、业务码、message 语义（除了本批新增的两个码）
- `requirements.txt`

## 七、验收标准

1. `pytest -q` ≥ 217；已有用例零改动。
2. 变异测试两条：把 `claim()` 里 `fingerprint` 比较删掉 → 用例 2 变红；把失败路径的 `release()` 删掉 → 用例 6 变红。
3. `alembic check` → 无差异（模型与迁移一致）。
4. `grep -rn "40903\|40904" app/` 只命中 `app/errors.py`。
