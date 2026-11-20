# PLAN — M2 第 7 批：把「玩家推进」从服务层接到 HTTP 层

> 上一份 PLAN（M2 第 6 批：上游错误映射收敛）已随提交 `d39759d` 落地，归档在
> `docs/exec-plans/completed/PLAN-m2-batch6-error-mapping.md`。
> 本批来源：工作区里已存在、但**没有任务书、没有 HTTP 出口**的那三个新文件。
> 本批**只做推进链路的收口**，不开新玩法。
> 本批起提交动作由 Hermes 执行（见 `docs/harness/agent-loop-playbook.md` R8）。

## 一、现状事实（已实测，别重新推理）

| 事实 | 证据 |
|---|---|
| `app/services/play_engine.py` 261 行，`advance_story()` 是唯一的推进入口 | 文件已读 |
| `app/services/conditions.py` 73 行，供 validator 与 play_engine 共用求值逻辑 | `blueprint_validator.py:5` 已 import |
| `tests/test_play_engine.py` 238 行 / 10 条测试，全绿 | 2026-11-20 Hermes 实跑 `168 passed, 1 warning in 6.37s`（第 6 批收工时是 158） |
| **`advance_story()` 零调用方**：除测试文件外无人 import | `grep -rn "play_engine" app/ tests/` 只命中 `tests/test_play_engine.py` |
| **没有任何推进端点**：现有路由只有 stories ×4 + story_plans ×1 | `grep -rn "@router\." app/api/` |
| 本批此前无任务书、无 `progress.md` 记录、`feature_list.json` 无对应条目 | 三份文件均已核对 |

**结论：这是一个"写了一半"的功能。** 服务层能算、能写事件日志、能判结局，但玩家在界面上没有任何地方能触发它。负责人早上的检查方式（看前后端功能有没有实现）会被这一条卡住，所以本批第一件事就是把这件事说清。

## 二、待负责人一句话确认的越界改动

工作区 `app/services/blueprint_validator.py` 被改了 **3 行 / 删 7 行**：
`_condition_matches()` 不再自己写五分支字典，改为转发到 `app/services/conditions.py` 的 `condition_matches()`。

- 行为等价：`168 passed`（含 validator 的 30 条历史用例）
- 与上一批 `provider_errors.py` 属同一类收敛：同一份知识只留一处
- 但这文件在历次收工记录里都出现在**禁改清单**里

→ Hermes 建议**保留**。负责人确认保留则记为已批准；不确认则在 T3 随本批一起回退这一处。

## 三、任务（按序执行，一次只做一件）

### T1 读懂门（负责人做，Hermes 只挑错、不代答）

`advance_story()` 是本项目的核心玩法执行器。在它接上 HTTP 之前，负责人必须能脱稿说清：

1. 玩家选了一个「不属于当前这一集」的选项时，会发生什么？数据库里会不会留下半条记录？
2. 玩家的两次选择之间，谁决定「现在该玩第几集」？如果库里被手工改成两集都是 `in_progress`，代码挑哪一集？
3. 某个选项写 `delta: +80`、当前值是 50，结果是多少？为什么不是 130？

三问答完、Hermes 挑完错，才进 T2。

### T2 定 URL 形态（两个方案，负责人选）

| 方案 | 形态 | 优点 | 缺点 |
|---|---|---|---|
| **A（推荐）** | `POST /api/stories/{public_id}/play`，body `{"choice_key": "..."}` | 名词清楚；以后加「回退一步」「跳过本集」都是同一资源的动作 | URL 不带剧集号，跨集判断只能靠服务层 |
| B | `POST /api/stories/{public_id}/episodes/{number}/choices/{choice_key}` | 语义最直白，天生拒绝跨集选错 | URL 长；换集逻辑散到路由层；每加一个动作要新开路径 |

### T3 实现端点（Claude Code）

- 新增 `app/api/play.py`（或并入 `stories.py`，由 T2 结果决定），挂到 `app/main.py`
- 复用 `get_db_session`；单事务；**不新增依赖**
- 响应体用 `PlayOutcome` 的字段显式拼，不直接 `return` dataclass

### T4 错误映射（单一事实来源）

`PlayError` 四个子类 → `AppError`，**只允许写在一处**（与 `provider_errors.py` 同一哲学）：

| 异常 | HTTP | 业务码 | 触发条件 |
|---|---|---|---|
| `StoryNotFound` | 404 | 沿用既有 40401 | public_id 不存在 |
| `StoryFinished` | 409 | 本批新定 | 故事已 completed / abandoned |
| `ChoiceNotInCurrentEpisode` | 400 | 本批新定 | 选项不属于当前集 |
| `NoMatchingEnding` | 500 | 本批新定 | 蓝图通过可达性校验后仍无结局 = 数据被手改 |

新业务码先在任务书里定好数字再写代码，不许边写边取。

### T5 测试（正常 1 条 + 失败 4 条 + 1 条事件可见）

- 正常：创建 → 连推到结局；`GET /api/stories/{id}/state` 能读到 `last_sequence` 增长
- 失败：404 / 已结局 / 跨集选错（断言**库内零新增行**）/ 无匹配结局
- 事件可见：推进后 `GET .../state` 的最近变化里出现 `choice_selected` 与 `metric_changed`

### T6 复验（Hermes，不采信任何 agent 自述）

- 全量 `pytest -q`，数字必须 ≥ 176（168 + 新增 ≥8）
- 变异测试：把 `_next_sequence` 的 `(last or 0) + 1` 改成 `(last or 0)` → 必须有测试变红，恢复后全绿
- 禁改比对：`app/schemas/story_blueprint.py`、`alembic/versions/`、已有测试预期零改动

### T7 落盘（Hermes）

`docs/harness/progress.md` 新增 Session 013；`feature_list.json` 新增 `sc-m2-07`，`passing` 必须带本轮真实数字。

## 四、禁改清单（本批）

- `app/schemas/story_blueprint.py`
- `app/services/blueprint_validator.py`（除第二节那处待确认的转发，不再动）
- `alembic/versions/` 下任何已发布迁移
- 任何已有测试的预期结果
- M1 阶段门与 `sc-m1-03` 状态

## 五、验收标准（负责人视角，不需要读代码）

1. 能一句话说清：**玩家在哪个 URL 做什么动作，返回什么**
2. 有一个真实可调的端点，正常路径与至少一条失败路径各有测试证据
3. 全量测试数字从 168 涨上去，且没有任何一条老测试被改预期
4. 负责人能脱稿答出 T1 的三问
