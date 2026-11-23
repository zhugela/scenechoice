# 失败模式与对策（Failure Catalog）

> 用途：这个项目踩过的坑，一条一条写清「现象 → 根因 → 规则 → 守门测试」。
> 每次收工/复审前扫一眼这张表。新增一条必须同时给出守门测试（没有测试的规则等于没有规则）。
> 来源：2026-11-20 ~ 11-23 的 M2/M3 开发与外部复审。

## 一、表：现象 → 根因 → 规则 → 守门

| # | 现象（会被什么抓到） | 根因 | 规则（以后照做） | 守门测试 |
|---|---|---|---|---|
| 1 | 外层事务 rollback 后库里居然还有数据 | pysqlite 惰性发 `BEGIN`；调用方还没写过东西时，第一条语句是 `SAVEPOINT`，SQLite 认为事务是它开的，`RELEASE` 直接提交，外层 rollback 变空操作 | 开嵌套事务前，若连接未在事务中，先显式 `BEGIN`（`story_store._start_outer_transaction`） | `test_save_blueprint_inside_outer_transaction_rolls_back_with_it` |
| 2 | 换后端（Postgres）会静默丢写 | 引擎靠「退出 savepoint 块」落库，而这只在 SQLite 上成立 | 事务边界由 service **显式** `commit()`，不依赖上下文管理器退出；谁提交写进 docstring | `test_engine_commits_and_leaves_no_transaction_open`（断言 `session.in_transaction() is False`） |
| 3 | JSON 列被改坏，接口返回 200 + 搅烂数据 | `list("abc")` 不报错，变成 `['a','b','c']`，pydantic 照收 | 从 JSON 列重建对象前做形状检查（`isinstance(list)` + 元素类型），不合格 → 受控 50003 | `test_get_story_with_scalar_json_personality_returns_500_50003` |
| 4 | 非法 JSON 让异常绕过损坏保护 | `JSONDecodeError` 在**查询阶段**抛出，早于重建代码 | 「查询 + 重建」整体纳入同一保护；宽 except 要含 `ValueError` | `test_get_story_with_corrupt_invalid_json_personality_returns_500_50003` |
| 5 | 一个玩家动作被生成 5 段旁白、扣 5 次钱 | 缓存键用了**请求参数**（sequence），而一次动作写 5 行事件 | 缓存/幂等键必须是「业务事实的唯一标识」（回合锚点 = `choice_selected.sequence`），不是请求参数 | `test_one_turn_is_narrated_once_for_any_of_its_rows` |
| 6 | 跨回合数值串味 | 按 sequence 聚合时没有上界 | 时间线类聚合必须同时有**下界与上界**（本回合开始 → 下回合开始） | `test_second_turn_prompt_does_not_leak_the_first_turn` |
| 7 | 加了一条迁移，已有测试红了 | 断言里硬编码了 head/版本号 | 结构性断言（head 是哪条）用代码动态取；测试断言**业务行为**而不是编号 | `_head_revision()` + 子进程 `alembic check` 守护 |
| 8 | 模型改了列、迁移没写，CI 全绿 | 只有人手动跑 `alembic check` | 模型与迁移一致性必须自动化守护，作为一条测试跑 | `tests/test_migration_guard.py` |
| 9 | 实现方「让测试过」的方式是改已有断言 | 缺契约变更的记录纪律 | 契约变更允许改断言，但必须**逐条列出改了哪行、为什么**；实现方自述不算证据 | 复审时看 `git diff -U0 tests/` 的删除行 |
| 10 | 实现方说「已验证」，实际没跑 | 自述与证据混同 | 完成判据三层：**文件存在 → 能编译 → 真跑出输出**；变异测试由**验收方**自己做 | 验收报告必须贴真实输出行 |
| 11 | 功能做完就标 passing，但负责人讲不清 | 状态口径与读懂门脱钩 | **用户可见行为 → `blocked`（等读懂门）**；纯测试/内部收敛/运维设置 → `passing` | `feature_list.json` 的状态与 `docs/learning/read-gate-*.md` 一一对应 |
| 12 | 同一份知识写两处，改一处漏一处 | 没有单一事实来源 | 业务码/错误映射/版本号/比较逻辑只留一处；用 `grep` 证明收敛 | 各批的 `grep` 验收项 |

## 二、编码代理（Claude Code / Codex）的已知行为

| 行为 | 对策 |
|---|---|
| 撞 `--max-turns` 上限报 `error_max_turns`（代码可能已完成） | 任务书里把「验证命令 + 预期数字」写死；撞上限后先看工作区与 pytest，再决定是否续跑 |
| 为了让测试过而改既有断言 | 任务书明写「只许追加」；验收时 `git diff tests/` 只看删除行 |
| 顺手加"更漂亮"的实现（如 serializer 强制 `+00:00`） | 验收时问一句「这是观感还是契约」；观感类改动默认退回 |
| 自述「已验证」 | 一律自己复跑，并做变异 |

## 三、每轮固定的验收动作（不可省）

1. 全量 `pytest -q`（数字必须往前走，且没有别的测试变红）
2. `python -m compileall -q app tests`
3. 涉及数据库 → `alembic upgrade head` + `alembic check`（现在有守护测试兜底）
4. 禁改清单 `git diff --stat`
5. **变异测试 ≥2 条**：把关键判断改坏 → 对应测试必须红 → 还原 → 复跑全绿 + `grep MUTATION` 零残留
6. 落盘 `progress.md`（证据只写真实跑出来的数字）+ `feature_list.json`（状态与证据一致）
7. 交付附「自查清单」，逐条填数字
