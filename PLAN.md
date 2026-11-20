# PLAN — M2 第 8 批：存档载入的版本契约 + 业务错误码单一来源

> 上一份任务书（第 7 批：玩家推进接 HTTP）已归档到
> `docs/exec-plans/active/PLAN-m2-batch7-play-http-endpoint.md` —— 那里仍挂着 `sc-m2-07`
> 的负责人读懂门（T1 三问），本批不动它，也不在 play 链路上叠加新东西。
> 本批来源：`docs/harness/reviews/latest.md` 剩下的 P2 + `progress.md` Session 013 登记的
> 「下批收敛 40401」。
> 本批提交动作由 Hermes 执行（`docs/harness/agent-loop-playbook.md` R8）。

## 一、现状事实（已实测，别重新推理）

| 事实 | 证据 |
|---|---|
| `blueprint_version` 只建列不读写 | `app/models/story.py:73` 只有 `default=1`；`grep -rn "blueprint_version" app/ tests/ alembic/` 除模型/迁移/测试建表语句外零命中 |
| 载入时既不比版本、也不兜形状错误 | `app/services/story_store.py:189` 裸 `StoryBlueprint(...)`；`app/middleware.py:25-31` 把任何异常兜成 `500 internal server error` |
| `40401` 有 3 处字面量 | `app/api/stories.py:137`、`:182`、`app/services/play_errors.py:42` |
| 基线 | 2026-11-20 `./docs/harness/init.sh` → `179 passed, 1 warning in 6.69s` |
| 旧版本存档 / 损坏存档的 API 路径零测试 | `grep -n "blueprint_version" tests/` 只命中 `test_migrations.py` 的建表 SQL |

**结论**：现在把一份旧形状存档交给 `GET /api/stories/{public_id}`，玩家看到的是
`500 internal server error`。既不能区分「旧版本」和「数据被改坏」，也没有任何修复指引。

## 二、本批做什么（两个单元，按序做完一个再动下一个）

### U1 版本契约（主功能）

- `app/services/story_store.py` 新增模块常量 `BLUEPRINT_VERSION = 1`：它描述「当前这份
  Pydantic 计划 schema 会长出什么样的行」，所以跟着映射代码放，不放进被禁改的 schema 文件。
- `save_blueprint` 落库时**显式**写 `blueprint_version=BLUEPRINT_VERSION`（不吃列默认值）。
- `load_blueprint` 先比版本：不相等 → 抛新异常 `BlueprintVersionError(stored, supported)`。
- 重建 `StoryBlueprint(...)` 时捕 `pydantic.ValidationError` → 抛 `BlueprintCorruptedError`。
- 路由映射（`app/api/stories.py`，与既有 `BlueprintStorageError -> 42201` 同一写法）：

| 异常 | HTTP | 业务码 | 为什么 |
|---|---|---|---|
| `BlueprintVersionError` | 409 | 40902 | 请求本身合法，是存档与当前契约不兼容 —— 冲突，不是客户端写错 |
| `BlueprintCorruptedError` | 500 | 50003 | 库被 API 之外改坏 = 服务端故障，不装成 4xx |

- OpenAPI 给 `GET /api/stories/{public_id}` 补 409 描述，文字与码一致。

### U2 业务错误码单一来源

- `app/errors.py` 新增常量：`STORY_NOT_FOUND=40401`、`PLAY_CHOICE_NOT_IN_EPISODE=40001`、
  `STORY_FINISHED=40901`、`STORY_VERSION_UNSUPPORTED=40902`、`NO_MATCHING_ENDING=50001`、
  `PLAY_ADVANCE_FALLBACK=50002`、`STORY_ARCHIVE_CORRUPTED=50003`，并注明「状态码 ×100 + 序号」。
- `app/api/stories.py`、`app/services/play_errors.py` 改为引用常量；**行为零变化**，
  OpenAPI 描述里给人看的数字照旧保留。
- 同步改 `play_errors.py` 顶部注释：单一来源从「本模块」上移到 `app/errors.py`。

## 三、测试（只新增，不改任何已有用例的预期）

1. `save_blueprint` 后直接查库列，`stories.blueprint_version == 1`。
2. 存好后 `UPDATE stories SET blueprint_version=0` → `GET /api/stories/{public_id}` →
   `409` + `40902`，message 是人话（不是 `internal server error`）。
3. 存好后把某个 JSON 列改成坏形状（例如把 `characters.personality` 写成字符串）→ 同端点 →
   `500` + `50003`。用例里要断言「这不再是裸 500/500」。
4. 既有 179 条必须全绿，一条预期都不许改。

## 四、禁改清单（本批）

- `app/schemas/story_blueprint.py`
- `app/services/blueprint_validator.py`、`app/services/play_engine.py`、`app/services/conditions.py`
- `alembic/versions/` 下任何已发布迁移（本批**不需要**迁移：列已存在）
- 任何已有测试的预期结果
- `requirements.txt`（不新增依赖）
- M1 阶段门、`sc-m1-03`、`sc-m2-07` 的状态

## 五、非目标（本批明确不做，登记在案）

| 项 | 为什么不做 |
|---|---|
| 角色 `secret` / 结局 `conditions` 是否下发、`public_id` 要不要 ownership 校验 | 两类方案（能力链接 vs 归属校验）各有代价，属产品决定，要负责人点头（playbook 第四节第 3 类） |
| `save_blueprint` 的 savepoint 三条测试 | 纯测试补充，留给下一批，避免本批同时改实现和补第三批入口的网 |
| WAL / `busy_timeout` / 幂等键 / 生成元信息落库 | 全是评审 P3，M3 前统一处理 |

## 六、验收标准（负责人视角，不需要读代码）

1. 一句话能说清：**拿一份旧版本存档的链接去请求，看到的是 409 + 40902 的人话提示，不再是 500。**
2. 全量 `pytest -q` 从 179 涨到 ≥182，且没有任何一条老用例被改预期。
3. 变异测试：把版本比较改成恒真 → 版本用例必须变红；还原后全绿。
4. 禁改清单文件 `git diff --stat` 为空。
