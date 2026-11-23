# PLAN — M3 第 1 批修复：旁白缓存键必须是「回合锚点」，不是「请求里的 sequence」

> 来源：仓库第 4 棒外部复审（P0-1）+ Hermes 独立复现。
> Hermes 复现证据（一次性探针，跑完即删）：一次 `advance_story("e1_truth")` 写了 6 行事件，
> 其中 5 行 `source=player`（seq 2..6）；对每一行各请求一次旁白 →
> **`narrations` 落 5 行、模型调用 5 次**，5 段不同文本。
> 「只生成一次」只在两次请求恰好用同一个 sequence 时成立 —— 而前端拿 `recent_changes`
> 或拿 `outcome.sequence` 都会落在不同行上，所以这不是边缘情况，是主路径。
> 基线：`6952d2c`，`237 passed`。

## 一、根因

`app/services/narrator.py` 里：
- `load_context()` 已经把上下文锚定到 `choice_event`（那个回合的 `choice_selected` 行）；
- 但缓存读写用的是**请求进来的** `sequence`（`_find_cached(..., sequence)` 与 `Narration(sequence=sequence)`）。

于是「上下文一样、键不一样」，一个回合被切成 5 段各自缓存。

## 二、要改成什么样

1. `load_context()` 在 `NarrationContext` 里多返回一个 `turn_sequence`：该回合 `choice_selected` 行的 sequence（即锚点）。
2. `generate()` 的缓存读取、落库、以及日志一律用 `context.turn_sequence`，**不再用请求参数**。
3. 端点响应里的 `sequence` 返回 `narration.sequence`，也就是锚点（客户端因此知道同一回合只对应一个值）。
4. 请求任意一行「属于这个回合的 player 事件」（seq 2..6）都必须命中同一段旁白；
   请求不属于任何回合的 player 行（如 seq 1 的 `story_status_changed` 且后面没有 choice）→ 仍 404/40402。

## 三、必须新增的测试（这是本批的验收核心）

1. **P0 守门测试**：一次推进后，分别请求 `choice_selected` 行的 sequence 与回合末 `outcome.sequence` →
   两次都 200、文本相同、响应 `sequence` 相同；`narrations` 表只有 **1** 行；假 client 调用 **1** 次。
2. **跨回合不串味**：连推两回合，第二回合的旁白 prompt **不含**第一回合的选项文本，
   且两回合各 1 行（共 2 行）。删掉 `load_context` 里 `next_choice_sequence` 那个上界 → 这条必须变红。

## 四、顺带要补的文档与守护（同批，别拖）

- `docs/harness/progress.md` 的 Session 022 已知风险里补：**最坏 90 秒**（3 次尝试 × 30s 客户端超时），
  并对「GET 有副作用（写库 + 花 token）」与「无鉴权」定级，写清处置计划（改 POST 或加 per-`public_id` 频率上限，二选一，写明选哪个、什么时候做）。
- 新增一条自动化守护：测试里跑 `python -m alembic check` 子进程，断言输出含
  `No new upgrade operations detected`。现在只有人手动跑，模型与迁移漂移没人拦。

## 五、允许修改

- `app/services/narrator.py`、`app/api/narrations.py`、`app/schemas/stories.py`（若响应模型需要说明）
- `tests/test_narrations.py`（**只允许**因为「响应 sequence 改为回合锚点」这一契约变化而调整断言，且必须在报告里逐条列出改了哪几行、为什么）
- `docs/harness/progress.md`、新增迁移守护测试文件

## 六、禁改清单

- `app/services/play_engine.py`、`story_planner.py`、`blueprint_validator.py`、`conditions.py`
- `app/schemas/story_blueprint.py`、`app/models/`、`alembic/`、`requirements.txt`
- `tests/` 下其它文件（`test_stories_api.py` / `test_play_api.py` / `test_idempotency.py` 一行都不许动）

## 七、验收标准

1. `pytest -q` ≥ 240，且除上面「契约变化」那几行外，没有别的已有断言被改。
2. 变异 A：把缓存键改回「请求 sequence」→ 新增的 P0 守门测试必须红。
3. 变异 B：删掉 `next_choice_sequence` 上界 → 跨回合测试必须红。
4. `python -m alembic check` 子进程守护测试存在且能拦住漂移（人工制造漂移验证一次：临时给模型加一列，守护必须红，然后还原）。
