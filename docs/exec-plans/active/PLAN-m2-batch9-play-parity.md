# PLAN — M2 第 9 批：推进接口的口径对齐（版本闸 + 拆蓝图异常映射）

> 上一份任务书（第 8 批：存档载入版本契约）已随提交 `acc139c` 落地；本批是它的两处
> 直接后果，来自 Session 015 合并 master 时发现的口径不一致。
> 本批提交动作由 Hermes 执行（`docs/harness/agent-loop-playbook.md` R8）。

## 一、现状事实（已实测）

| 事实 | 证据 |
|---|---|
| 合并后基线 | `7c0ae28` 上 `.venv/Scripts/python.exe -m pytest -q` → `194 passed, 1 warning in 6.74s` |
| 推进链路不校验存档版本 | `advance_story()`（`app/services/play_engine.py:138`）取到 story 后直接判 `FINISHED_STATUSES`；`grep -rn "BLUEPRINT_VERSION" app/` 只有 `story_store.py` |
| 详情接口与推进接口口径不一致 | 详情接口对旧版本存档给 `409/40902`（第 8 批），同一个存档走 `/play` 却照旧推进 |
| 引擎会抛未映射的 `BrokenBlueprint` | `app/services/play_engine.py:59`；`grep -n "BrokenBlueprint" app/services/play_errors.py` → 零命中，落进 50002 兜底网，码名是「story could not be advanced」，玩家看不出是存档坏了 |

## 二、本批做什么（三个单元）

### U1 推进链路加版本闸（唯一允许碰 play_engine 的一处）

`advance_story()` 取到 `story` 之后、判 `FINISHED_STATUSES` 之前，插入：

```
if story.blueprint_version != BLUEPRINT_VERSION: raise UnsupportedBlueprintVersion(...)
```

- 新异常 `UnsupportedBlueprintVersion(PlayError)`，与既有四个子类同一形状。
- `BLUEPRINT_VERSION` 从 `app/services/story_store.py` import（无循环：store 不 import engine）。
- **为什么破例改 play_engine**：另一条路是在路由里先查一次存档再调引擎——那会把「按 public_id 取存档」
  拆成两处、多一次查询，而且第二个取数点将来照样会漂移。本批只允许在取到 story 之后加这几行，
  推进逻辑（指标夹取、结局判定、事件日志）**一行不许动**，交付时要给 `git diff` 证明。

### U2 两类引擎异常进映射表（单一事实来源）

| 异常 | HTTP | 业务码 | 为什么 |
|---|---|---|---|
| `UnsupportedBlueprintVersion` | 409 | `40902`（复用第 8 批的 `STORY_VERSION_UNSUPPORTED`） | 与详情接口同一件事，同一个码；请求合法，是存档与当前契约不兼容 |
| `BrokenBlueprint` | 500 | `50003`（复用 `STORY_ARCHIVE_CORRUPTED`） | 存档内部不一致（如选项引用不存在的指标）= 库外改坏，与详情接口的「存档损坏」是同一类故障 |
| 其余未知 `PlayError` | 500 | `50002` | 只剩真正的兜底网 |

- OpenAPI：`PLAY_409_DESCRIPTION` 写清 `40901`（已结局）/ `40902`（旧版本）；
  `PLAY_500_DESCRIPTION` 写清 `50001`（无匹配结局）/ `50003`（存档损坏）。数字照旧写给人看。

### U3 测试（只追加 `tests/test_play_api.py`，不改任何已有用例）

1. 把存档 `blueprint_version` 改成 0 后推进 → `409` + `40902`，且**库内零新增行**（沿用既有「零新增」断言写法）。
2. 把某选项 `effects` 的 `metric_key` 改成不存在的 `ghost` 后推进 → `500` + `50003`。
3. 既有 `40901`（已结局）、`50001`（无匹配结局）、`40001`（跨集）用例必须原样全绿。

## 三、禁改清单

- `app/schemas/story_blueprint.py`、`app/services/blueprint_validator.py`
- `app/services/play_engine.py`：**除 U1 那几行外一行不许动**
- `app/services/conditions.py`、`app/models/`、`alembic/`、`requirements.txt`
- 任何已有测试的预期结果、`tests/test_play_engine*.py`
- M1 阶段门、`sc-m1-03`、`sc-m2-07`、`sc-m2-08` 的状态

## 四、验收标准

1. 一句话说清：**旧版本存档现在在详情和推进两个入口都被同一个 409/40902 挡住；存档内部不一致时，
   推进接口返回 500/50003，而不是含糊的 50002。**
2. 全量 `pytest -q` 从 194 涨到 ≥197，已有用例零改动。
3. 变异测试：版本闸改 `if False:` → 用例 1 变红；删掉 `BrokenBlueprint` 分支 → 用例 2 变红。
4. `git diff app/services/play_engine.py` 只有版本闸那几行。
