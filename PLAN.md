# PLAN — M3 第 1 批：把「玩家的一次选择」变成一段叙事（narration）

> 负责人 2026-11-22 明确：口述稍后补，先继续开发。读懂门记录仍在
> `docs/learning/read-gate-m2.md`，未作废。
> M2 功能项已齐（`sc-m2-05/06/07/08/09/10/11/12/13/14`）。本批起进入 M3 第一片。
> 基线：`a6010d1`，`220 passed`。

## 一、为什么是这个切片

M3 的目标是「玩家能读到一个故事」。推进引擎已经能把状态改对（`play_engine`），
但玩家看到的是数字变化，不是故事。这一批只做**最小可读**：给某一次推进，生成一段
人话叙述，并且**同一段只生成一次**（缓存），不让玩家每刷新一次就烧一次 token。

不做的事（明确留到后面）：流式输出、多结局文本变体、前端、RAG 记忆、语气定制。

## 二、数据层（新增一张表，迁移 `2026xxxx_0004_add_narrations.py`）

`app/models/narration.py` → `Narration`，表名 `narrations`：

| 列 | 类型 | 约束 |
|---|---|---|
| `id` | Integer PK | |
| `story_id` | FK → `stories.id`，ON DELETE CASCADE | 非空 |
| `sequence` | Integer | 非空，指 `story_state_changes.sequence`（这次推进的那条事件） |
| `text` | Text | 非空 |
| `model` | String(80) | 非空（哪个模型写的） |
| `prompt_tokens` / `completion_tokens` | Integer | 可空（这次生成花了多少） |
| `created_at` | DateTime | 非空，UTC |

唯一约束：`(story_id, sequence)` —— 一条事件只应该有一段叙述。
关系：`Story.narrations`（级联删除）。

## 三、提示词 `app/prompts/narration.py`

- `SYSTEM_PROMPT`：写清「你是互动短剧的旁白」。硬性要求：
  - 只输出**纯文本**，不要 Markdown、不要 JSON、不要标题、不要引号包裹
  - 120～400 个汉字（太短没信息量，太长玩家不读）
  - **第二人称**（「你」）描写玩家刚才的选择带来了什么，落到具体动作/对白/环境，不要复述数字
  - 不得出现「指标」「数值」「+10」这类游戏系统词
- `build_messages(context: dict) -> list[dict]`：输入是剧情上下文（见下），输出 messages。
  上下文包含：故事标题/类型/主题、当前集的目标与冲突、本集人物名单（**只给名字与角色，不给 secret**）、
  玩家选的那句话、这次选择的后果提示（`consequence_hint`）、指标变化后的**语义描述**
  （like「声望明显上升」而不是「reputation 62」）。
- 明确一条：`secret` 永远不进这个 prompt —— 玩家还没解锁的秘密不能借旁白的嘴说出来。

## 四、服务 `app/services/narrator.py`

- `load_context(session, public_id, sequence) -> NarrationContext | None`
  - 存档不存在 → `None`
  - 版本不支持 → 抛 `BlueprintVersionError`（复用 `story_store` 的那个，上层映射成 409/40902）
  - 事件不存在（sequence 超范围 / 不是玩家事件）→ `None`
- `generate(session, public_id, sequence, *, client, max_attempts=3) -> Narration`
  - 已有缓存 → 直接返回，**不调模型**
  - 没缓存 → 构建 messages → 调 `client.complete()` → 校验输出 → 落库（同一事务）
  - 校验失败（含 Markdown 围栏 / JSON / 字数越界）→ 把失败原因作为修复指令重试，最多 3 次；
    3 次都不过 → 抛 `NarrationRejected`
  - `DeepSeekClientError` 原样抛出，由路由层翻译（复用 `provider_errors`）
- 校验函数 `validate_narration(text) -> list[str]`（返回问题列表，空表示通过）单独可测。

## 五、端点

`GET /api/stories/{public_id}/narrations/{sequence}`

| 情况 | 响应 |
|---|---|
| 首次生成 | `200`，`data: {public_id, sequence, text, model}` |
| 已有缓存 | `200`，同一份文本（不调模型） |
| 存档不存在 | `404` + `40401` |
| 版本不支持 | `409` + `40902` |
| 事件不存在 | `404` + `40402`（新增码：这条事件没有可叙述的内容） |
| 模型 3 次都被拒 | `422` + `42202`（新增码：旁白不合规，已重试 3 次） |
| 上游错误 | 走既有 `provider_error_to_app_error` |

新增业务码一律进 `app/errors.py`（`NARRATION_EVENT_NOT_FOUND = 40402`、`NARRATION_REJECTED = 42202`），路由里不许写字面量。

## 六、测试（新文件 `tests/test_narrations.py`，全离线，用假 client）

1. 首次生成：假 client 返回合法文本 → 落库；`narrations` 表 1 行；响应含 `text`/`model`。
2. 回放：同参数再请求一次 → 文本相同，且**假 client 的调用次数没有增加**（这是本批的核心断言）。
3. 模型返回带 ` ``` ` 围栏 → 重试；修好后成功（断言调用次数 = 2）。
4. 模型 3 次都不合法 → `422` + `42202`，且**没有落库**。
5. 存档不存在 → `404` + `40401`。
6. `sequence` 不存在 → `404` + `40402`。
7. 存档版本被改成 0 → `409` + `40902`。
8. `validate_narration` 单元测试：Markdown 围栏、JSON、过短、过长、正常文本。
9. prompt 不含 `secret`：构造一个带 secret 的蓝图，断言 `build_messages` 的文本里没有那个 secret 字符串（防未来顺手把整份蓝图塞进 prompt）。

## 七、禁改清单

- `app/services/play_engine.py`、`app/services/story_planner.py`、`app/services/blueprint_validator.py`、
  `app/services/conditions.py`、`app/schemas/story_blueprint.py`
- 已发布迁移（只许新增 0004）
- 任何已有测试的预期结果（`tests/test_migrations.py` 的 head 断言已是动态的，不需要改）
- `requirements.txt`

## 八、验收标准

1. `pytest -q` ≥ 229（9 条新增起），已有用例零改动。
2. `alembic upgrade head` 实跑成功；`alembic check` 无差异。
3. 变异测试两条：
   - 把「已有缓存直接返回」删掉 → 用例 2 变红（证明回放断言不是摆设）
   - 把 `validate_narration` 改成恒返回空列表 → 用例 3、4 变红
4. `grep -rn "40402\|42202" app/` 只命中 `app/errors.py`。
