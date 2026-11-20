# PLAN — M2 第 10 批：只做「不加新用户可见行为」的收尾

> 前一份任务书（第 9 批）已随提交 `98c3cc4` 落地。
> 本批**故意不加任何新功能**：读懂门队列已有 3 批（`sc-m2-07` / `sc-m2-08` / `sc-m2-09`），
> 按 playbook R7 不能再往负责人头上叠新行为。本批只补测试网、收字面量、去掉一处隐患。

## 一、现状事实

| 事实 | 证据 |
|---|---|
| 收工基线 | `98c3cc4` 上 `.venv/Scripts/python.exe -m pytest -q` → `197 passed, 1 warning in 7.30s` |
| `save_blueprint` 的 savepoint 分支零测试 | `app/services/story_store.py:148-150` 有 `session.begin_nested()` 分支；`grep -n "begin_nested\|savepoint" tests/` 零命中（评审 P2 原文：这是第 3 批把保存嵌进更大事务的入口） |
| `provider_errors` 里仍是字面量 | `app/services/provider_errors.py` 里 `42201 / 50201 / 50202 / 50204 / 50302 / 50303` 直接写在代码里，而 `app/errors.py` 已经是业务码唯一来源（第 8 批定了 7 个常量） |
| 版本闸有两处，没有一致性测试 | 详情接口在 `app/api/stories.py`、推进引擎在 `app/services/play_engine.py`；同一个旧存档在两个入口必须是同一个 `(409, 40902)`，现在没有任何测试同时打两边 |
| `play_engine` 为拿一个常量 import 整个 `story_store` | `app/services/play_engine.py:32`；方向没环，但没人守，将来 store 反向 import 就会当场炸 |

## 二、本批做什么（四件，全是「不改对外行为」）

### U1 savepoint 三条测试（只加测试，不改实现）

新增测试（放 `tests/test_stories_api.py` 或新建 `tests/test_story_store_savepoint.py`，你定，理由写进报告）：

1. 外层事务内调用 `save_blueprint` 后**外层 rollback** → 7 张业务表全部 0 行。
2. 外层事务内调用 `save_blueprint` 后**外层 commit** → 故事整树落库（行数断言照既有写法）。
3. savepoint 内失败（用既有 `after_flush_postexec` 钩子在同一故事树上抛错）→ 外层事务**仍可用**：随后能正常 commit 另一条记录，且失败那棵树零残留。

### U2 业务码字面量收敛

- `app/errors.py` 补齐 `provider_errors` 需要的常量（沿用「状态码 ×100 + 序号」命名）：
  `42201 / 50201 / 50202 / 50204 / 50302 / 50303`。
- `app/services/provider_errors.py` 改为引用常量；**对外行为零变化**，OpenAPI 描述里的数字照旧保留。
- 顺手核对：`grep -rn "42201\|50201\|50202\|50204\|50302\|50303" app/` 收敛后字面量只应出现在 `app/errors.py`（与第 12 轮那次 provider 收敛同一标准）。

### U3 双端版本闸一致性测试

新增 1 条测试：存好一个故事 → 把 `blueprint_version` 改成 0 →
`GET /api/stories/{id}` 与 `POST /api/stories/{id}/play` **两边都**返回 `409` 且 `code == 40902`，
且两边 message 都能被人读懂（不含 `internal server error`）。

### U4 把 `BLUEPRINT_VERSION` 挪到中立模块

- 新增 `app/blueprint_contract.py`，只放 `BLUEPRINT_VERSION` 与一句说明（为什么这个版本号管的是
  「写进 SQL 行的 JSON 形状」，不归 schema 也不归某个 service）。
- `story_store.py`、`play_engine.py` 改为从这里 import，`play_engine` 不再 import `story_store`。
- 验证：`grep -n "story_store" app/services/play_engine.py` → 零命中；`python -c "import app.main"` 通过。

## 三、禁改清单

- 任何**对外行为**（状态码、业务码、message、响应体字段）
- `app/schemas/story_blueprint.py`、`app/services/blueprint_validator.py`、`app/services/conditions.py`
- `app/models/`、`alembic/`、`requirements.txt`
- 任何已有测试的预期结果
- `sc-m1-03` / `sc-m2-07` / `sc-m2-08` / `sc-m2-09` 的状态

## 四、验收标准

1. 全量 `pytest -q` 从 197 涨到 ≥201（U1 三条 + U3 一条），且已有用例零改动。
2. `grep -rn "50201\|50303\|42201" app/` 只命中 `app/errors.py`。
3. 变异测试两条：把 `save_blueprint` 的 `session.begin_nested()` 改成 `session.begin()` → U1 至少一条变红；把详情接口的版本闸改 `if False:` → U3 变红。
4. `grep -n "story_store" app/services/play_engine.py` 零命中。
