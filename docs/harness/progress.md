# 进度日志

<!--
每次开工先读这个文件，收工写完再走。任何 coding agent 都不会自动维护它，
只有 AGENTS.md 里明确要求了，agent 才会读/写。
-->

## 当前已验证状态

- 仓库根目录：`D:\zhugela-hub\scenechoice`
- 标准启动路径：`.venv/Scripts/python.exe -m uvicorn app.main:app --reload`
- 标准验证路径：`.venv/Scripts/python.exe -m pytest -q`（2026-11-22：210 passed）
- 自动检查：push/PR 走 `.github/workflows/ci.yml` + `.github/workflows/ai-review.yml`（AI 审查 + CI 失败诊断），说明见 `docs/harness/ai-review.md`
- 一键体检：`./docs/harness/init.sh`（在 git-bash 里跑；会装依赖 + 跑全部测试 + 打印启动命令）。`check.ps1` 当前有仓库根定位 bug，修复前请勿作为有效体检依据
- 当前最高优先级未完成功能：`sc-m1-03` 负责人个人掌握验收（学习清单 6 项未勾）；M2 第 7/8/9 批（`sc-m2-07` 推进端点、`sc-m2-08` 版本契约、`sc-m2-09` 口径对齐）代码已完成并验证，**三批都在等负责人读懂门（队列 3 批）**；第 10 批（`sc-m2-10`）是纯收尾，无新用户可见行为，已 passing
- 当前 blocker：M1 阶段门卡在"个人掌握"这一条，实现与真实评测两条已过
- M2 第 1 批数据层骨架（2026-11-15）：已建库验证；SQLAlchemy 2.1.8 + Alembic 1.20.1，迁移 `20261115_0001`，7 张业务表 + 1 张 Alembic 记账表，`alembic check` 无差异，121 passed

## 会话记录

### Session 021（M2 第 14 批：POST 幂等键，方案 A）

- 日期：2026-11-22
- 目标：`POST /api/stories` 接受 `Idempotency-Key`，同一 key 重发回放首次响应、不重复扣 token、不重复建存档。负责人当天选 A。
- 执行：Claude Code 一轮（4 分 22 秒，中途 codex 那轮被中止、工作区零残留）→ Hermes 复验 + 两次变异 + 一处测试改法修正。
- 基线：`f2a386b`，`210 passed`。

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `app/models/idempotency.py`（新增，76 行） | `idempotency_records` 表：`(scope,key)` 唯一、`fingerprint`、`state`（pending/completed）、`status_code`、`response_body`、时间戳 | 回放要先能存下"第一次的响应长什么样"；`scope` 防不同端点共用同一个 key 撞车 |
| `alembic/versions/20261122_0003_add_idempotency_records.py`（新增） | 建表 + 唯一约束 | 迁移只加不改，已发布的两个版本没动 |
| `app/services/idempotency.py`（新增，339 行） | `request_fingerprint`（规范化 JSON + sha256）、`claim`（两轮：读→判；插入撞唯一约束则 rollback 后重读赢家）、`_reset_stale`（`UPDATE ... WHERE state='pending' AND updated_at < cutoff`，`rowcount==1` 才算抢到）、`complete` / `release`（`WHERE` 带 ownership token） | 并发下不能把 `IntegrityError` 抛成 500；10 分钟过期要能重置但不能两个请求同时重置；生成超时的旧请求不能覆盖别人的响应 |
| `app/api/stories.py` | 读 `Idempotency-Key` 头；`mismatch→409/40903`、`in_progress→409/40904`、`replay→原状态码+响应体+`Idempotent-Replay: true``、`claimed→生成→complete`；失败路径 `release`；把生成逻辑抽成 `_plan_and_store` | 无 key 时行为必须与之前完全一致，所以只有"带 key"这条路进新逻辑 |
| `app/errors.py` | 新增 `IDEMPOTENCY_KEY_REUSED = 40903`、`IDEMPOTENCY_IN_PROGRESS = 40904` | 业务码唯一来源规则 |
| `tests/test_idempotency.py`（新增 9 条） | 回放同一 public_id、换 body 409、pending 未过期 409、过期重置、无 key 照旧两份、失败释放、超长 key 422、并发撞唯一约束、迁移建表唯一约束 | 覆盖 PLAN 第七节全部验收点 |
| `tests/test_migrations.py`（Hermes 修正） | 把硬编码的 `assert revision == "20261122_0003"` 改成 `_head_revision()`（读 alembic script directory 的 head） | Claude Code 为了让测试过，直接把已有断言里的迁移版本号改掉了 —— 这违反了"不许改已有测试预期"，而且每加一条迁移都要再改一次，审查时还会被标成可疑改动。改成动态取 head 后，这类改动不再需要动测试 |

- 验证证据（Hermes 实跑）：
  - 全量：`219 passed, 2 warnings in 14.04s`（基线 210，净增 9）
  - `.venv/Scripts/python.exe -m alembic upgrade head` → 真实执行成功；`alembic check` → `No new upgrade operations detected.`
  - **变异 O**（`_judge` 里去掉 fingerprint 比较）→ `1 failed`，红的正是"同 key 换 body → 409/40903"
  - **变异 P**（失败路径去掉 `release`）→ `2 failed`，含"失败后同 key 可重试"
  - 还原后 `grep MUTATION` 零残留，复跑 219 passed
  - `grep -rn "40903\|40904" app/` → 只命中 `app/errors.py`
- 已知风险：
  - `asyncio.CancelledError` 属 `BaseException`，请求被取消时不走 `release()`，该 key 会 pending 最多 10 分钟（Claude Code 自己登记的）。
  - `completed` 记录没有清理任务：表会一直长。M3 前要加 TTL 清理（例如按 `created_at < now - 7d` 删除）。
  - 回放的是**存下来的响应体**，不含后续状态变化；如果将来响应里加"当前进度"这类字段，回放就会过期。
  - 幂等只在单进程内靠数据库唯一约束保证；多进程同样成立（约束在库里），但没有真起进程的并发测试。
- 下一步最佳动作：M2 的功能项到此齐了。剩下的是人的关：读懂门队列 3 批（7/8/9），以及 M3 前的清理任务（幂等表 TTL、secret/ownership 方案）。

### Session 020（M2 第 13 批：时间戳带时区）

- 日期：2026-11-22
- 目标：对外时间戳从 SQLite 读回的 naive UTC 恢复为带 `+00:00` 的 aware UTC，字段、状态码、业务码与 message 全部不变。
- 基线：`e6160e2` + 当前 PLAN 工作区，`pytest -q` → `207 passed`。
- 改动：`app/models/base.py` 新增 `as_utc()`；`app/api/stories.py` 的列表摘要与状态变化时间戳经它归一化；`app/schemas/stories.py` 用 JSON `field_serializer` 输出显式 UTC 偏移；新增 3 条时间戳测试；`docs/RELIABILITY.md` 写明 API 时间戳契约。
- 验证：
  - 全量：`.venv/Scripts/python.exe -m pytest -q` → `210 passed, 1 warning in 9.35s`
  - `.venv/Scripts/python.exe -m compileall -q app tests` → 通过
  - 变异：`as_utc()` 临时改为原样返回 → 新增 3 条用例全红；还原后全量复跑绿
  - TestClient 手工样例：`created_at=2026-11-22T03:14:35.077118+00:00`
- 环境说明：Git Bash 的 `init.sh` 因共享 `uv` 缓存锁权限失败；pytest 使用 `.pytest-cache/harness-tmp` 并设置 `TEMP`/`TMP`/`PYTEST_DEBUG_TEMPROOT` 避开全局临时目录权限错误。
- **实现方变化**：`claude` CLI 的原生二进制损坏（`claude native binary not installed`），本批由 codex 实现，Hermes 独立复验。
- **Hermes 复验后的一处否决**：codex 在 `app/schemas/stories.py` 加了两处 `field_serializer`，只为把 Pydantic 默认的 `Z` 改成 `+00:00` —— 代价是 `app/schemas` 反向 import `app/models`（分层倒置）+ 序列化里用 `assert`（`-O` 下会被剥掉）。收益仅是观感，已删除；契约改为「必须带偏移，`Z` 与 `+00:00` 都合法」。
- Hermes 复验：`pytest -q` → `210 passed, 1 warning in 8.89s`；`compileall` 通过；**变异 N**（`as_utc()` 改成直接返回入参）→ `3 failed`（三条新用例全红），还原后零残留、复跑 210 passed。
- 未做：未执行 `git add` / `git commit` / `git push`。
- 下一步最佳动作：M2 剩余 P3 只剩 POST 幂等键；读懂门队列仍是 3 批（7/8/9），更该先清。

### Session 019（M2 第 12 批：SQLite 并发与持久化设置）

- 日期：2026-11-20
- 目标：把评审 P3「只开了 foreign_keys，没有 WAL / busy_timeout」补上，不加新用户可见行为。
- 执行：Claude Code 一轮（1 分 51 秒）→ Hermes 复验 + 收窄一处异常捕获 + 两次变异。
- 基线：`0aaa272`，`204 passed`。

| 文件 | 改了什么 | 为什么 |
|---|---|---|
| `app/db.py` | 新增 `SQLITE_BUSY_TIMEOUT_MS = 5000`；连接监听每个 SQLite 连接都设 `PRAGMA busy_timeout`；新增 `_enable_sqlite_wal()` 对**文件库**执行一次 `PRAGMA journal_mode=WAL`，返回非 `wal` 只记 warning；新增 `_is_memory_database()` 跳过内存库 | 默认 rollback journal 下多写会 `database is locked`；`busy_timeout` 管「等锁多久」，与 SQLAlchemy `connect_args` 的连接超时不是一个旋钮，这条区别写进了常量注释 |
| `app/db.py`（Hermes 收窄） | `except Exception` → `except (SQLAlchemyError, sqlite3.Error, OSError)` | 原写法把编码错误、拼写错误也吞成一条 warning，启动照跑、问题推迟到首个请求才暴露；收窄后库里/文件系统问题仍不阻止启动，代码 bug 会当场炸 |
| `docs/RELIABILITY.md` | 新增「SQLite concurrency assumptions」一节：WAL 下读写不互相阻塞但**写仍是单写者**、`-wal`/`-shm` 备份要一起拷、M3 多进程部署前必须重读 | 这类假设不写下来，半年后换部署方式时没人记得 |
| `tests/test_db_settings.py`（新增 3 条） | 文件库 WAL + busy_timeout 读回；内存库仍是 `memory` 但仍设 busy_timeout；两个连接各读一次证明监听对每个连接生效 | 只断言「读回常量」会在常量被改成 0 时自己骗自己，所以额外断言常量 > 0 |

- 验证证据（Hermes 实跑）：
  - 全量：`207 passed, 1 warning in 8.92s`（基线 204，净增 3）
  - `compileall app tests` → 通过
  - **变异 L**（`SQLITE_BUSY_TIMEOUT_MS` 改 0）→ `1 failed`；**变异 M**（删掉 WAL 切换调用）→ `1 failed`；两次还原后 `grep MUTATION` 零残留，复跑 207 passed
  - `grep -rn "busy_timeout\|journal_mode" app/ --include=*.py` → 只命中 `app/db.py`
  - 仓库根无 `-wal`/`-shm` 残留（测试库都在 `tmp_path`）
- 已知风险：
  - `engine` 在**导入时**就会连一次库把 journal_mode 设成 WAL（此前是惰性连接）。任何「import 不碰库」的假设不再成立；CI/脚本里若 cwd 不同，会在那里创建一个空库文件（已 gitignore）。
  - WAL 是**文件属性**，一次设置长期有效；测试断言的是「设置后读回 wal」，没有断言「重启后仍是 wal」（那是同一件事，但没测）。
  - `busy_timeout` 只在连接建立时设，不做动态调整；多进程写会排队等 5s，超时后仍是 `database is locked`。
  - 没有并发写的实测（两个进程同时写、验证排队而非报错）——那需要一个真起线程/进程的测试，属集成测试范畴，本批未做。
- 下一步最佳动作：M2 剩余 P3 = POST 幂等键、时间戳带时区；或者清读懂门（队列仍是 3 批）。

### Session 018（M2 第 11 批：PR AI 审查回灌）

- 日期：2026-11-20
- 触发：PR #6 上 `github-actions[bot]` 的 AI 审查给了 2 条阻塞。Hermes 过滤后两条都算「建议看代价」，采纳并回灌。
- 基线：`43801d6`，`201 passed`。

| 审查意见 | Hermes 复核结论 | 处置 |
|---|---|---|
| 路由里 `session.commit()` 违反「api 只收参数调 service」 | 成立：`advance_story` 里 `with transaction:` 退出时已经处理提交，路由那句多余；而且**谁负责提交这件事没有任何测试钉住** | 删掉路由的 commit；**把 commit 移进引擎**（见下）；补 3 条测试 |
| 两个入口的版本比较看不到共用同一份逻辑 | 成立（异常类型按层分开是对的，比较逻辑重复了） | `blueprint_contract.version_is_supported()` 成为唯一比较点，store 与 engine 都改用它 |

- 本轮最关键的一处（不是审查提的，是回灌时自己撞出来的）：
  - Claude Code 删掉路由 commit 后自己发现：请求路径里 `advance_story` 之前的 SELECT 已经触发 autobegin，所以 `in_transaction()` 为真 → 走 **`begin_nested()`**；SQLite 上 `RELEASE` 恰好会提交（就是 Session 017 那个坑），所以 203 条测试全绿，**但这是靠 SQLite 的怪癖侥幸落库**。换到事务立即开始的后端（Postgres/MySQL），释放 savepoint 只合并不提交，请求 session 关闭时回滚 —— 玩家的操作会**静默丢失**。
  - 处置：在 `advance_story` 的 `with transaction:` 块之后显式 `session.commit()`，注释写清「不要依赖 savepoint 释放」。新增 `test_engine_commits_and_leaves_no_transaction_open`：断言引擎返回后 `session.in_transaction()` 为 **False** —— 这条断言才是「真的提交了」，SQLite 的怪癖骗不过它。
- 验证证据（Hermes 实跑）：
  - 全量：`204 passed, 1 warning in 7.48s`（基线 201，净增 3）
  - `compileall app tests` → 通过；`grep -n "session.commit()" app/api/play.py` → 零命中
  - `grep -n "blueprint_version != " -r app/` → 零命中（比较只剩 `blueprint_contract.py`）
  - **变异 K**（删掉引擎里那句 `session.commit()`）→ `1 failed, 17 passed`，红的正是 `test_engine_commits_and_leaves_no_transaction_open`；还原后复跑 204 passed，`grep MUTATION` 零残留
  - 独立探针（Hermes 手写脚本，跑完即弃）：`advance_story` 返回后 `session.in_transaction()` 为 False，新会话能看到 6 条事件行、指标 `reputation=62`
- 已知风险：
  - 引擎现在无条件 `session.commit()`：将来若有人想把 `advance_story` 嵌进更大的事务（比如「推进 + 记积分」原子提交），需要再加 `commit: bool = True` 参数，否则会被引擎提前提交。目前只有一个调用方（play 路由），没有这个需求。
  - `begin_nested()` 分支仍然存在（请求路径永远走它，因为 SELECT 已 autobegin）；它的意义是「部分失败不污染请求事务」，但没有任何测试从 Postgres 角度验证过。
  - AI 审查里还提到「`get_db_session` 异常路径是否 rollback」：`app/db.py:33` 是 `with SessionLocal() as session:`，`Session.__exit__` 会 close → 回滚未提交事务，结论是安全的；已用新会话零新增行测试间接钉住。
- 下一步最佳动作：PR #6 已 `CLEAN`（CI + AI 审查都绿）。剩余可做项都是 M2 的 P3（WAL/busy_timeout、幂等键、时间戳带时区）；但更该做的是清读懂门（队列 3 批）。

### Session 017（M2 第 10 批：只做收尾，不加新行为）

- 日期：2026-11-20
- 本轮目标（一句话）：补上 `save_blueprint` savepoint 分支的测试网、把剩下的业务码字面量收干净、给版本闸加一条双端一致性测试、把 `BLUEPRINT_VERSION` 挪到中立模块。**不加任何新用户可见行为**（读懂门队列已有 3 批）。
- 执行方式：`PLAN.md` 写任务书 → Claude Code 一轮（4 分 24 秒）→ Hermes 独立复验 + 三次变异。
- 基线：`98c3cc4`，`197 passed`。

| 单元 | 文件 | 改了什么 | 为什么 |
|---|---|---|---|
| U1 savepoint 测试 | `tests/test_stories_api.py`（+129） | 三条：外层 rollback → 7 表 0 行；外层 commit → 整树落库；savepoint 内失败 → 外层仍可用且失败那棵零残留 | 评审 P2 点名「这个分支是第 3 批把保存嵌进更大事务的入口，零测试」 |
| U1 顺带修的真 bug | `app/services/story_store.py` | 新增 `_start_outer_transaction()`：savepoint 分支里若 DBAPI 连接还没开事务（SQLite），先显式 `BEGIN` | **测试第一次跑就红**：pysqlite 懒开事务，调用方还没写过东西时，第一条语句就是我们的 `SAVEPOINT`；SQLite 对「由 savepoint 自己开启的事务」执行 `RELEASE` 时直接提交，调用方的 `rollback()` 变空操作 → docstring 承诺的 all-or-nothing 不成立。这是修 bug，不是改设计 |

### U2 业务码收敛 / U3 双端一致性 / U4 契约常量

| 单元 | 文件 | 改了什么 | 为什么 |
|---|---|---|---|
| U2 | `app/errors.py`、`provider_errors.py`、`api/stories.py`、`api/story_plans.py`、`dependencies.py` | 补齐 7 个 provider 侧常量（42201/50201/50202/50204/50301/50302/50303），全部改为引用；行为零变化 | `app/errors.py` 已是唯一来源，这些字面量是最后一批残留 |
| U3 | `tests/test_play_api.py`（+35） | 一条：同一旧版本存档，详情与推进**两边**都 409 + 40902 | 版本闸有两处，之前没有任何测试同时打两边 |
| U4 | `app/blueprint_contract.py`（新增）+ `story_store.py`、`play_engine.py` | `BLUEPRINT_VERSION` 挪到中立模块，`play_engine` 不再 import `story_store` | 上批遗留的风险：engine 为一个常量 import 整个 store，方向没有测试守着，反向 import 就会成环 |

- 验证证据（Hermes 实跑）：
  - 全量：`201 passed, 1 warning in 7.44s`（基线 197，净增 4）
  - `compileall app tests` → 通过；`.venv/Scripts/python.exe -c "import app.main"` → 通过
  - **变异 H**（删掉 `_start_outer_transaction(session)` 调用）→ `1 failed, 200 passed`，红的正是 `test_save_blueprint_inside_outer_transaction_rolls_back_with_it`（证明这条测试真能抓住那个静默提交）
  - **变异 I**（`begin_nested()` 改 `begin()`）→ `3 failed`，三条 savepoint 用例全红
  - **变异 J**（详情接口版本闸换错异常）→ `1 failed`，红的正是双端一致性用例
  - 三次还原后 `grep MUTATION app tests` 零残留，复跑 201 passed
  - 单一来源：`grep -rn "42201\|50201\|50202\|50204\|50301\|50302\|50303" app/ --include=*.py` 只命中 `app/errors.py`（7 行）
  - `grep -n "story_store" app/services/play_engine.py` → 零命中
- 已知风险：
  - 修复靠 pysqlite 的私有属性 `driver_connection.in_transaction` 判「是否已开事务」。SQLAlchemy 或 pysqlite 升级后要重看；非 SQLite 走 early return，**Postgres 上没验证过**（M2 没有 Postgres）。
  - 「外层先写过一条 DML 再 savepoint」这条路径本来就没问题（Claude Code 单独验证过），现在也没有专门的测试钉住它；变异 H 只覆盖了「外层还没写」。
  - 本轮破例允许改实现（PLAN 原本写「U1 只加测试」）：因为测试第一次就跑红，暴露的是真 bug 而不是测试写错。已按 playbook 第四节第 4 类（禁改清单越界要说清为什么）记录在此。
  - 读懂门队列仍是 3 批（7/8/9），本批没有新增用户可见行为，所以不追加；但 `_start_outer_transaction` 这处修复是「最难自己看出来」的一段代码，建议列进读懂门的第 4 题。
- 下一步最佳动作：M2 剩余 P3（WAL / busy_timeout、幂等键、时间戳带时区）都是**不加新玩法**的小口子，可继续；但更值得做的是先清读懂门。

### Session 016（M2 第 9 批：推进接口口径对齐）

- 日期：2026-11-20
- 本轮目标（一句话）：把「旧版本存档」和「存档内部不一致」在推进接口上的口径，对齐到详情接口已经定好的 40902 / 50003；不开新玩法。
- 执行方式：`PLAN.md` 写任务书 → Claude Code 一轮（2 分 16 秒）→ Hermes 独立复验 + 两次变异。
- 基线：合并 master 后 `7c0ae28`，`.venv/Scripts/python.exe -m pytest -q` → `194 passed`。

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/services/play_engine.py` | 新增 `UnsupportedBlueprintVersion(PlayError)`；`advance_story` 取到 story 之后加 4 行版本闸；`advance_story` 的 docstring 补列这两个异常（docstring 由 Hermes 补，Claude Code 按「只加版本闸」的约束没敢动） | 推进链路原本完全不看 `blueprint_version`，同一个旧存档在详情接口被 40902 挡住、在推进接口照旧执行。**破例改引擎的理由**：替代方案是在路由里再查一次存档，那会把「按 public_id 取存档」拆成两处，第二个取数点将来照样漂移 |
| `app/services/play_errors.py` | `UnsupportedBlueprintVersion → 409/40902`；`BrokenBlueprint → 500/50003`；两条 OpenAPI 描述同步写清四个码 | master 的引擎会抛 `BrokenBlueprint`（选项引用不存在的指标），此前没有映射，落进 50002 兜底网，玩家看到的是「story could not be advanced」，等于把「存档坏了」伪装成「未知故障」 |
| `tests/test_play_api.py`（只追加） | 3 条：旧版本推进 → 409/40902 且零写入；选项引用 ghost 指标 → 500/50003（显式断言不是 50002）；OpenAPI 描述含 40902/50003 | 前两条各守一条新分支；第三条守文档口径不漂 |

- 验证证据（Hermes 实跑）：
  - 全量：`197 passed, 1 warning in 7.31s`（基线 194，净增 3）
  - `compileall app tests` → 通过
  - **变异 F**（版本闸改 `if False:`）→ `1 failed`，红的正是 `test_old_blueprint_version_returns_409_40902_and_writes_nothing`
  - **变异 G**（`BrokenBlueprint` 分支短路）→ `1 failed`，红的正是 `test_broken_choice_effect_returns_500_50003_instead_of_the_fallback`
  - 两次还原后 `grep MUTATION` 零残留，复跑 197 passed
  - `git diff app/services/play_engine.py`：只有 import 一行 + 异常类 6 行 + 版本闸 7 行 + docstring 3 行
  - 禁改比对（`app/schemas`、`blueprint_validator.py`、`conditions.py`、`app/models`、`alembic`、`requirements.txt`、`tests/test_play_engine*.py`）→ 空
- 已知风险：
  - `play_engine` 现在 import `story_store`（只为一个常量），模块加载变重；目前无环（store 不 import engine），但**没有测试守着这个方向**，将来谁在 store 里 import engine 就会当场炸——上策是把 `BLUEPRINT_VERSION` 挪到中立模块，留给下一批。
  - 版本闸现在有**两处**（详情接口一处、推进引擎一处），同一个常量同一个码，但缺一条「双端一致性」测试（第 6 批给 provider 错误矩阵做过同类网）——下一批补。
  - `BrokenBlueprint` 与 `BlueprintCorruptedError` 共用 50003，但两条消息不同（`cannot be opened` / `cannot be advanced`）；这是有意的：码表示「存档坏了」，消息说清坏在哪个动作上。
  - **读懂门队列已经 3 批（7、8、9）**，按 playbook R7 都不该在答完前继续叠加新功能。
- 下一步最佳动作：不再开新功能。批次 10 只做「不加新用户可见行为」的收尾：`save_blueprint` 的 savepoint 三条测试、`provider_errors` 里 `42201/502xx/503xx` 字面量收敛、双端版本闸一致性测试。

### Session 015（合并 origin/master，解 PR #6 冲突）

- 触发：PR #6 建好后 GitHub 报 `CONFLICTING`。原因是 master 上另有两条线先落地——批次 6 的错误映射收敛（`55fd3cf` / `a77d599`）与 M3 选择执行引擎（`057a1f0` / `eac0a6d` / `50bc9ff`，经 PR #5 合入）。其中 M3 引擎与本分支 `b6d89c9` 的「play engine 服务层回滚点」是同一条河的两次改道。
- 冲突 7 个文件，逐个判（类：disjoint / 同题两答 / 被取代）：

| 文件 | 类 | 处置与理由 |
|---|---|---|
| `app/services/play_engine.py`（add/add） | 同题两答 | **取 master**：master 是超集（多 `BrokenBlueprint`、指标夹取、集数连续性校验），且带 `tests/test_play_engine.py` 344 行 + `test_play_engine_transaction.py` 93 行；本分支那份是 `b6d89c9` 明确标注的「仅作回滚点」 |
| `app/services/conditions.py`（add/add） | 同题两答 | **取 master**：82 行版本同时服务 validator 与 engine，接口更完整 |
| `tests/test_play_engine.py`（add/add） | 同题两答 | **取 master**：覆盖更全，本分支 10 条是它的子集 |
| `app/services/blueprint_validator.py` | disjoint（同一意图） | 两侧都把 `_condition_matches` 改成转发 `conditions.py`；取 master 的一行别名（`_condition_matches = condition_matches`）比本分支的包装函数更短。**副产品**：Session 013 挂着的「validator 越界改动待确认」现在有独立证据——两条线各自独立做了同一处收敛，予以保留 |
| `PLAN.md`、`docs/harness/feature_list.json`、`docs/harness/progress.md` | 被取代 | **保留本分支**：master 侧是批次 6 的旧任务书（已归档在 `docs/exec-plans/completed/PLAN-m2-batch6-error-mapping.md`），本分支带着 Session 014 与批次 8 的新记录 |
| `app/api/stories.py`、`tests/test_stories_api.py`、`tests/test_retryable_status_source.py`、`app/services/provider_errors.py` | disjoint | git 自动合并，无需人工介入 |

- 合并后验证：`.venv/Scripts/python.exe -m pytest -q` → **194 passed, 1 warning in 7.12s**（187 + master 带来的 engine/transaction 测试）
- 合并顺带暴露两条待办（进批次 9）：master 的引擎会抛 `BrokenBlueprint`（存档内部不一致，如选项引用了不存在的指标），`play_errors` 目前没映射它 → 落到 50002 兜底网；另外推进接口仍不校验 `blueprint_version`，与详情接口口径不一致。

### Session 014

- 日期：2026-11-20
- 本轮目标（一句话）：M2 第 8 批 —— 把「存档载入」的版本契约补上，并把业务错误码收敛成单一来源；不开新玩法、不动 play 链路。
- 执行方式：`PLAN.md` 写任务书 → 实现由 Claude Code（`claude -p`，四轮，合计约 6 分钟）→ Hermes 独立复验 + 五次变异测试 + 一次「漏网形状」探针 → Codex 外部审查一轮。
- 基线：`./docs/harness/init.sh` → `179 passed, 1 warning in 6.69s`（开工前实测）。

| 单元 | 文件 | 改了什么 | 为什么这么改 |
|---|---|---|---|
| U1 版本契约 | `app/services/story_store.py` | 新增 `BLUEPRINT_VERSION = 1`、`BlueprintVersionError`、`BlueprintCorruptedError`；`save_blueprint` 显式写 `blueprint_version`；`load_blueprint` 先比版本，重建段捕 `(ValidationError, KeyError, IndexError, TypeError, AttributeError)` | `blueprint_version` 此前只建列不读写，旧形状存档会让玩家看到裸 `500 internal server error`，无法区分「旧版本」和「数据被改坏」 |
| U1 路由映射 | `app/api/stories.py` | `GET /api/stories/{public_id}` 捕两类异常 → `AppError(409/40902)`、`AppError(500/50003)`，均 `raise ... from exc`；OpenAPI 补 409 描述 | 与既有 `BlueprintStorageError → 42201` 同一写法；版本不兼容是冲突（409）不是客户端写错，库外改坏是服务端故障（500） |
| U2 错误码单一来源 | `app/errors.py`、`app/api/stories.py`、`app/services/play_errors.py` | 7 个业务码常量（40401/40001/40901/40902/50001/50002/50003）；两处路由由字面量改为引用常量，OpenAPI 描述保留给人看的数字 | 此前 `40401` 有 3 处字面量，改一处漏一处就会漂移；行为零变化 |
| 测试 | `tests/test_stories_api.py`（只追加） | 5 条新增（3 条 U1 + 1 条参数化 2 case） | 版本不匹配、pydantic 拦得住的损坏、pydantic 拦不住的损坏，三条路径各有断言 |

- 打回与修复（这一轮真正的教训）：
  - 第一轮交付只捕 `ValidationError`。Hermes 用一次性探针实测另外两种形状：`endings.conditions = '"oops"'` → **裸 500/500**；`choices.effects` 缺 `metric_key` → **直接把 `KeyError` 抛穿路由**（靠中间件兜）。
  - 判为本批阻塞（U1 的定义就是「库外改坏要给 50003 人话」），第二轮扩捕到 5 类异常并补 1 条参数化用例；探针文件用完即删，未入库。
- 验证证据（全部由 Hermes 实跑，不采信 agent 自述）：
  - 全量：`.venv/Scripts/python.exe -m pytest -q` → **`187 passed, 1 warning in 6.81s`**（基线 179，净增 8）
  - 编译：`.venv/Scripts/python.exe -m compileall -q app tests` → 通过
  - **变异 A**（版本比较改 `if False:`）→ `1 failed, 26 passed`，红的正是 `test_get_story_with_unsupported_blueprint_version_returns_409_40902`；还原后 sha 回 `b8eb8194df4c7093`
  - **变异 B**（`except ValidationError` 改成 `except ZeroDivisionError`）→ `1 failed`，红的正是损坏用例
  - **变异 C**（except 元组只留 `ValidationError`）→ `2 failed`，红的正是新增参数化两例
  - **变异 D**（`_require_string_list` 只 `return list(value)`，拿掉形状检查）→ `1 failed`，红的正是 `test_get_story_with_scalar_json_personality_returns_500_50003`
  - **变异 E**（宽 except 去掉 `ValueError`）→ `1 failed`，红的正是 `test_get_story_with_corrupt_invalid_json_personality_returns_500_50003`
  - 五次变异每次还原后 sha 一致（终态 `8643805cdbbd1cc1`），`grep MUTATION` 零残留，复跑 187 passed
  - 禁改比对：`git diff --stat app/schemas/story_blueprint.py app/services/blueprint_validator.py app/services/play_engine.py app/services/conditions.py alembic/ requirements.txt` → 空
  - 老用例零改动：`tests/test_stories_api.py` 的 diff 只有 import 增一行 + 文件末尾追加，无删除行

##### Codex 外部审查（第 4 步，`codex exec review --uncommitted`）

结论：`overall_correctness = patch is correct`；4 条、无阻塞（其中 1 条 P2 是真漏洞）：

| 级别 | 问题 | 处理 |
|---|---|---|
| P2 | `list(...)` 不是形状检查：JSON 列被改成字符串时 `list("abc")` → `['a','b','c']`，pydantic 照收，详情接口返回 **200 + 搅烂的数据** | **已修**：新增 `_require_string_list()`，`isinstance(list)` + 每元素 `isinstance(str)`，否则 50003；补 `test_get_story_with_scalar_json_personality_returns_500_50003` |
| P2 | `feature_list.json` 同时挂两个 `in_progress`，违反自身 `single_active_feature` 与 AGENTS.md:28 | **已修**：`sc-m2-07` / `sc-m2-08` 都置 `blocked`（阻塞项=负责人读懂门），notes 写明 |
| P3 | `.claude/settings.local.json.bak-before-deny` 未跟踪且未被忽略，`git add -A` 会带进仓 | **已修**：`.gitignore` 增 `.claude/`，`git check-ignore` 验证命中 |
| P3 | 详情端点返回 500/50003 但 OpenAPI 只声明 404/409 | **已修**：补 500 描述（含 `50003`），补 `test_get_story_openapi_declares_archive_corruption_500` |

- 第四轮（Claude Code）：把 `session.scalar()` 一并纳入 try、宽 except 加 `ValueError`（覆盖 `json.JSONDecodeError`），并把 `BlueprintVersionError` / `BlueprintCorruptedError` 用 `except ...: raise` 提前原样放行 —— 否则版本不匹配会被误转成 50003。补 `test_get_story_with_corrupt_invalid_json_personality_returns_500_50003`。
- 已知风险：
  - `50003` 现在覆盖「JSON 列被改坏」的主要形状，但仍不是「任何损坏」：顶层类型正确、嵌套字段语义不对（如 `delta` 不是整数）会走 pydantic 或业务逻辑，没有逐字段交叉校验。
  - `BLUEPRINT_VERSION` 只有一个值 `1`，没有升级/回填路径；它与 alembic 迁移无机制关联，将来改 schema 要人工记得同步。
  - 40902 的 message 把服务端支持的版本号告诉客户端（等于公开契约版本），可接受但要知道。
  - 本批**未做**：角色 `secret` / 结局 `conditions` 是否下发、`public_id` 要不要 ownership（PLAN 第五节非目标，属产品决定，等负责人选方案）；`save_blueprint` 的 savepoint 三条测试；WAL/`busy_timeout`/幂等键/生成元信息落库。
  - `provider_errors.py` 与 `create_story` 里的 `42201 / 502xx / 503xx` 仍是字面量（本批允许改的文件不含 `provider_errors.py`），下一批再收。
  - **推进接口不校验版本**：`POST /api/stories/{public_id}/play` 走 `play_engine` 自己的取值路径，不经过 `load_blueprint`。所以一份旧版本存档在详情接口会被 409 挡住，在推进接口却照旧执行（读到的是 `current_value` / `episode.status` / `effects` JSON）。要一致就得把版本检查下沉到「按 public_id 取存档」的唯一入口，下一批处理。
  - `sc-m2-08` 仍为 `in_progress`：负责人读懂门没做，按 R7 不进 `passing`。
- 下一步最佳动作：负责人答第 8 批读懂门三问（见交付报告）；答完把 `sc-m2-07` / `sc-m2-08` 一并置 `passing`。下一批候选：`secret`+ownership 方案（要负责人选 A/B）、savepoint 三条测试、`provider_errors` 字面量收敛。

### Session 013

- 日期：2026-11-20
- 本轮目标（一句话）：把负责人的 Agent Loop 规则固化成文件、给工作区里「无任务书」的 play engine 补任务书并建立回滚点；**不开新功能实现**。
- 基线：`.venv/Scripts/python.exe -m pytest -q` → `168 passed, 1 warning in 6.37s`（第 6 批收工时 158，净增 10 条来自 `tests/test_play_engine.py`）
- 本轮做的三件事：

| 动作 | 产出 | 为什么 |
|---|---|---|
| 固化负责人 11-20 口述的四个答案 | `docs/harness/agent-loop-playbook.md`（R1–R9 + 9 步流程 + 四类停手条件 + 自查清单模板） | 负责人不看代码、不看 diff，交付标准必须写死成「可观察证据 + 自查清单」，否则每轮都要重新讨论 |
| 换任务书 | `PLAN.md` → M2 第 7 批；第 6 批归档到 `docs/exec-plans/completed/PLAN-m2-batch6-error-mapping.md` | 上次覆盖 PLAN 丢了历史（Session 007 已记录该风险），这次先归档 |
| 建回滚点 | `b6d89c9`（代码检查点）、`b1c62b7`（文档） | 此前 4 个文件一直未提交，改坏了无处可退 |

- 本轮查到的关键事实：
  - **`app/services/play_engine.py` 的 `advance_story()` 零调用方**：`grep -rn "play_engine" app/ tests/` 只命中测试文件；`app/api/` 现有路由仅 stories ×4 + story_plans ×1 → 推进功能只有服务层，玩家没有任何入口，属「写了一半」。
  - `app/services/blueprint_validator.py` 被上一轮改了 3+/7-（`_condition_matches` 改为转发 `conditions.py`）。行为等价、`168 passed` 兜底，但该文件在历次禁改清单内，等负责人一句话确认保留或回退。
  - `.claude/` 仍未跟踪且未被 `.gitignore` 覆盖（Session 007 已记录，未处理）。
- 约束遵守情况：未实现新功能；未改 M1 阶段门与 `sc-m1-03`；未改任何已有测试预期；未 push。
- 已知风险：`b6d89c9` 提交的是负责人尚未读懂的代码，仅作回滚点，不代表已验收；读懂门（T1）未过之前不得在其上叠加新实现。
- 下一步最佳动作：负责人答 `PLAN.md` 第三节 T1 的三问（Hermes 只挑错、不代答）；通过后选 T2 的 URL 方案 A/B，再由 Claude Code 实现端点。

#### 第二轮（同日，负责人授权自主执行：`Run this plan ... don't ask me anymore`）

负责人明确要求「按计划自己跑完、不要再问」，因此本轮的 T2–T7 由 Hermes 自主决策并执行；**T1 读懂门仍未完成，仍挂在负责人身上**。

| 决策 / 动作 | 内容 | 依据 |
|---|---|---|
| T2 URL 形态 | 选方案 A：`POST /api/stories/{public_id}/play`，body `{"choice_key": "..."}` | 与既有 `/api/stories` 前缀一致；未来「回退一步」「跳过本集」可在同一资源上加动作 |
| T4 错误码 | `40001` 跨集选错 / `40901` 已结局 / `50001` 无匹配结局 / `50002` 兜底 / 沿用 `40401` | 与既有「状态码 ×100 + 序号」规则一致（40401、42201、50201…） |
| 新增文件 | `app/api/play.py`（46 行）、`app/services/play_errors.py`（57 行）、`tests/test_play_api.py`（11 条） | T3/T4/T5 |
| 改动文件 | `app/main.py`（+2 行挂载路由）、`app/schemas/stories.py`（+3 个契约模型） | 同上 |

- 验证证据（全部由 Hermes 实跑）：
  - 新测试单跑：`pytest -q tests/test_play_api.py` → `11 passed, 1 warning in 0.99s`
  - 全量：`pytest -q` → **`179 passed, 1 warning in 6.57s`**（基线 168，净增 11）
  - 编译：`python -m compileall -q app tests` → 通过
  - **变异 1**（`play_engine.py:90` 把 `(last or 0) + 1` 改成 `(last or 0)`）→ `13 failed, 166 passed`；还原后 sha256 前 16 位回到 `0a584642ce0c64e7`，`grep MUTATION` 零残留，复跑 `179 passed`
  - **变异 2**（`play_errors.py` 把 `code=40001` 改成 `40002`）→ `1 failed, 10 passed`（红的正是跨集用例）；已还原
  - 禁改比对：`git diff --stat app/schemas/story_blueprint.py alembic/ requirements.txt app/services/blueprint_validator.py` → 空
  - 单一事实来源：`grep -rn "40001\|40901\|50001\|50002\|40401" app/` → 新码只出现在 `app/services/play_errors.py`（`40401` 在 `app/api/stories.py` 有 2 处既有字面量，留给下一批收敛）
- 已知风险：
  - 推进接口不是幂等重放：客户端超时重试会多消耗一集（与 Session 009 记录的 POST 风险同类）。
  - 接口仍无鉴权与归属校验，`public_id` 就是能力凭据（Session 003/010 已记录，未变）。
  - `40401` 现有 3 处字面量（`stories.py` ×2 + `play_errors.py` ×1），下批收敛到 `app/errors.py` 常量。

##### Codex 外部审查（第 4 步，`codex exec review`）

结论：**零阻塞**。1 条 P2 + 2 条 P3 已按「阻塞必修、建议看代价」处理：

| 级别 | 问题 | 处理 |
|---|---|---|
| P2 | 500 回滚测试只断言状态，未断言事件行数 / `last_sequence` / 指标 | **已修**：请求前后快照三者并逐一断言，用例改名为 `..._rolls_every_thing_back` |
| P3 | `50002` 兜底码在本端点不可达，却被写进 OpenAPI 500 描述 | **已修**：描述只保留 `50001`；代码保留兜底并注明「未来子类的防御网」 |
| P3 | 模块注释声称「错误码只出现在此」，但 `40401` 在 `stories.py` 仍有 2 处 | **已修**：注释限定为「play 专用码的单一来源」，并把 `40401` 收敛登记为下批工作 |

- 补做的变异测试（证明新断言不是摆设）：在 `advance_story` 里插入 `session.commit()` 模拟「边推边存」的部分提交 bug → `5 failed, 6 passed`，其中 `test_no_matching_ending_returns_500_and_rolls_every_thing_back` 变红；还原后 sha256 前 16 位回到 `0a584642ce0c64e7`，`grep MUTATION` 零残留。
- 复验：`pytest -q` → `179 passed, 1 warning in 6.62s`；`compileall` 通过。

- 下一步最佳动作：负责人做 T1 读懂门三问（`PLAN.md` 第三节）；通过后把 `sc-m2-07` 置 passing，再开下一批（`40401` 收敛 + 鉴权/归属校验）。

### Session 012

- 日期：2026-11-18
- 本轮目标（一句话）：按 `PLAN.md`（M2 第 6 批）把「上游错误 → 应用错误」映射收敛成一份共享函数，并补全 `/api/stories` 的错误码矩阵。
- 执行方式：由 agentloop 中台第 `#32` 轮派给 Claude Code（4 分 41 秒，$1.9976），本人（Hermes）逐条验收。
- 基线：`.venv/Scripts/python.exe -m pytest -q` → `153 passed`

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/services/provider_errors.py`（新增，71 行） | 唯一一份 `provider_error_to_app_error(exc) -> AppError`，并把两句 OpenAPI 描述一并搬进同模块 | 这份知识属于「产品策略层」：给定上游失败，我们要对调用方暴露什么码。放 service 层，客户端不感知我们的业务码，两个路由共用同一份 |
| `app/api/stories.py` | 删掉整段重复映射（−77 行），改为调用共享函数并 `raise ... from exc` | 原先分支链与 preview 逐条重复，且副本丢了异常链 `from exc`；收敛后不会再出现「只改一侧」的漂移 |
| `app/api/story_plans.py` | 同样改为调用共享函数（−54 行） | 对外行为零变化，只是把知识搬到一处 |
| `tests/test_stories_api.py`（+45） | 错误矩阵由 7 组扩到 10 组，补 403/408/429/500；新增异常链测试 | 评审指出的覆盖缺口；异常链测试是「副本曾丢 chain」的唯一回归网（`tests/test_stories_api.py:518` 断言 `__cause__`） |
| `tests/test_retryable_status_source.py`（+94 −32） | 一致性测试同时打 `/api/story-plans/preview` 与 `/api/stories` | 只有两个端点对同一状态码给出相同 `(status, code, message)` 才算真的没漂移 |

- 验收证据（全部由 Hermes 本人执行，不采信 agent 自述）：
  - 全量：`.venv/Scripts/python.exe -m pytest -q` → `158 passed, 1 warning in 6.06s`
  - **变异测试**：把 `and not is_retryable_status(exc.status_code)` 临时改成 `and True` → `5 failed, 153 passed`（红的正是 408/429 两组矩阵用例与双端一致性测试）；还原后 `158 passed`，文件 sha256 前 16 位回到 `b44c7636...`，`grep MUTATION` 零残留
  - 单一事实来源：`grep -rn "50302\|50303\|50201\|50202\|50204" app/` 只命中 `app/services/provider_errors.py`，两个路由文件零残留
  - 禁改文件：`blueprint_validator.py`、`story_blueprint.py`、`alembic/`、`docs/` 零改动
  - 双端一致性测试单跑耗时 `2.02s`（未打 slow 标记）
- 已知风险或未解决问题：
  - `docs/harness/reviews/latest.md` 里剩余 P2 未做：`blueprint_version` 只建列不读写（旧存档会 500）、`save_blueprint` 的 savepoint 分支零测试、恢复接口原样返回角色 secret 且无归属校验
  - 本轮改动尚未经本人逐行 review，提交由本人决定
- 下一步最佳动作：本人 review `app/services/provider_errors.py` 与两份测试改动后决定是否合入 master；之后按评审剩余 P2 继续，`sc-m1-03` 个人掌握验收仍是 M1 阶段门的唯一 blocker。

### Session 011

- 日期：2026-11-18
- 本轮目标（一句话）：把仓库接上「push/PR 自动检查」，并顺手修掉 master 上已经红了三天的 CI。
- 基线：master 最新提交 `bf59f40` 的 CI 是 `7 failed, 134 passed`；本地 `.venv/Scripts/python.exe -m pytest -q` 为 `141 passed`（修在本地未提交）。
- 根因：`bf59f40` 提交了迁移 `20261116_0002`、`tests/test_stories_api.py` 和 service，但漏提交 `app/models/ending.py` 与 `app/models/story.py`，master 上的 `Ending` 没有 `position` 字段，测试构造 `Ending(position=...)` 直接 `TypeError`。

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/models/ending.py`、`app/models/story.py` | 补提交 `position` 列与 `(position, priority)` 排序 | 已提交的迁移和测试依赖它们；不补 CI 永远红 |
| `scripts/ai_review.py`（新增） | 把 PR diff / CI 失败日志交给模型，按项目硬规则产出四节结论并评论 | 光有 CI 只会显示「红了」，没人说清红在哪、为什么 |
| `.github/workflows/ai-review.yml`（新增） | `pull_request` 审改动；`workflow_run` 在 CI 失败后诊断 | 触发点是 push/PR，不是手动喊 |
| `docs/harness/ai-review.md`（新增） | 触发点、一次性配置、故意不做的事、成本 | 面试要讲得清「为什么不让 AI 自己改自己审」 |
| `tests/test_ai_review.py`（新增 12 条） | 重试 / 脱敏 / 跳过 / 空日志 / 上下文拼接 | 闸门自己坏了没人知道 |

- 运行过的验证：
  - `.venv/Scripts/python.exe -m pytest -q` → `153 passed, 1 warning`
  - master `ef6d264` CI → success
  - PR #2 上 `github-actions[bot]` 贴出真实模型审查（连跑三轮，逐轮修掉了重试、脱敏、行号定位三类问题）
  - 临时分支造一次必挂测试：CI `failure` → `诊断 CI 失败` job 贴出根因与日志证据；验证完分支已删
- 已知风险或未解决问题：
  - 模型会编：第一轮 8 条「阻塞问题」里约 2 条是错的（例如断言 `actions/checkout@v7` 不存在——CI 真跑在 v7 上）。结论必须人过滤，不能当门禁。
  - 仓库 Actions secret 已配 `DEEPSEEK_API_KEY`（用的项目自带 key）。要换：`gh secret set`；要删：`gh secret delete`。
  - `.claude/` 仍是未跟踪目录，未处理。
- 关于 dsh-superagent（本次被问到的「superagent」）：本机只有源码和 `dsh` CLI，**没有 `superagent` profile**，且缺 `tmux` 和独立的机器人 GitHub 账号；它的触发方式是「白名单用户 @ 它」，不是「一 push 就动」。本轮按路线 A 做 Actions，未安装它。
- 下一步最佳动作：`sc-m1-03` 个人掌握验收（6 项自查 + 脱稿讲 M1 数据流）仍是 M1 阶段门的唯一 blocker；AI 审查保持现状观察一周，噪声大再考虑去掉 `synchronize` 事件。

### Session 010

- 日期：2026-11-16
- 本轮目标（一句话）：按 `PLAN.md` 修存档状态无法恢复的 P1，以及 endings 回读丢失合法数组顺序的 P2；不处理其余 P2/P3。
- 基线：`.venv/Scripts/python.exe -m pytest -q` → `137 passed, 1 warning`。全局临时目录的 pytest 清理仍有无权访问链接，使用仓库内 `--basetemp` 取得有效退出码；没有改测试预期来绕过环境问题。
- 改了哪几个文件、每处为什么这么改：

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/schemas/stories.py` | 新增动态状态、指标状态、剧集状态、变化记录和响应契约 | 静态蓝图与玩法进度职责分开；状态响应只公开当前进度需要的字段 |
| `app/services/story_store.py` | 新增 `load_story_state`；保存 endings 时写入数组下标 `position` | 动态状态按 `public_id` 单独读取；SQL 行没有天然顺序，必须显式保存数组位置 |
| `app/api/stories.py` | 新增 `GET /api/stories/{public_id}/state`，支持 `change_limit=1..100`，默认返回最近 20 条变化 | 采用 PLAN 推荐方案 A：详情继续返回静态蓝图，状态端点用于恢复和后续轮询 |
| `app/models/ending.py` | 新增 `position` 列及非负约束，解释 position 与 priority 的不同用途 | `priority` 是结局判定顺序，不保证数组升序；两者不能混用 |
| `app/models/story.py` | endings 关系改按 `(position, priority)` 排序 | 新数据按保存下标恢复；老数据 position=0 时仍按 priority 兜底 |
| `alembic/versions/20261116_0002_add_ending_position.py`（新增） | 在旧表上补 `position`，服务端默认 0；未修改已发布的 `20261115_0001` | SQLite 旧数据必须有可用的非空默认值；batch 模式保证列和 CHECK 可升级 |
| `tests/test_stories_api.py` | 新增状态恢复/404/OpenAPI 测试与乱序 priority 往返测试 | 钉住 `current_value=7`、剧集非初始状态、变化顺序及 `[2,1,3]` 数组顺序 |
| `tests/test_migrations.py`（新增） | 先用真实 Alembic 建到旧版本、插入已有结局，再升级 head | 证明迁移不只对空库可用；旧行升级后 position=0，并可优先按 priority 回退 |
| `docs/harness/progress.md`、`docs/harness/feature_list.json` | 记录本轮验证事实与 M2 第 5 批完成状态 | 跨会话状态必须与真实测试和迁移结果一致 |

- P1 实测证据：测试中先通过 `POST /api/stories` 创建故事，再直接修改库中 `reputation.current_value=7`、第 1 集状态为 `completed`、故事状态为 `in_progress`，追加 sequence 2；调用状态接口后读回 7、completed、in_progress、last_sequence=2，最近变化为 `[2,1]`。静态蓝图接口仍返回 `initial_value=50`。
- 状态枚举事实：PLAN 示例写的是 `episode.status='played'`，当前真实模型和数据库 CHECK 只允许 `planned/in_progress/completed`。本轮没有放宽约束或伪造 `played`，用合法的 `completed` 验证非初始状态可读回。
- endings 证据：同一 blueprint 的 endings priority 为 `[2,1,3]`，保存后重新加载 `model_dump()` 完全相等，id 顺序保持 `comeback/quit/survive`。
- 迁移证据：临时库从 `20261115_0001` 升级到 `20261116_0002`，升级前已有 3 条 endings；升级后 revision=`20261116_0002`，三行 position 均为 0，按 `(position, priority)` 顺序为 `quit/comeback/survive`。项目 `scenechoice.db` 也从 `20261115_0001` 成功升级。
- 跑过的验证和结果（真实数字）：
  - P1 红：`3 failed, 136 passed`（接口和 OpenAPI 尚不存在）
  - P1 绿：`139 passed, 1 warning`
  - endings 红：`1 failed, 139 passed`（旧关系按 priority 重排）
  - 模型修正后：`1 failed, 140 passed`（只剩迁移尚未创建）
  - 全量：`.venv/Scripts/python.exe -m pytest -q --basetemp .pytest-tmp/migration-green` → `141 passed, 1 warning in 4.65s`
  - `.venv/Scripts/python.exe -m compileall -q app tests` → 通过
  - `.venv/Scripts/python.exe -m alembic upgrade head` → `20261115_0001 -> 20261116_0002` 成功
  - `.venv/Scripts/python.exe -m alembic check` → `No new upgrade operations detected.`
- 约束遵守情况：
  - 未改 M1 preview、既有测试预期、已发布的 `20261115_0001` 迁移或其他 P2/P3。
  - 未执行 `git add` / `git commit` / `git push`。
  - M1 阶段门与 `sc-m1-03` 个人掌握验收未改变。
- 已知遗留风险：
  - 状态接口没有鉴权；`public_id` 仍是恢复凭据，M3 玩家界面前需决定能力链接或归属校验。
  - 最近变化默认 20 条，可调 1..100；没有完整历史分页。
  - 迁移保留数据库级 position 默认 0，模型也默认 0；新建故事会显式写真实下标。
- 下一步最佳动作：本人 review 状态接口、endings 顺序和两份新增/更新测试后决定是否提交；之后按下一批处理评审剩余 P2。

### Session 009

- 日期：2026-11-16
- 本轮目标（一句话）：按 `PLAN.md` 完成 M2 第 2 批 Repository、存档/恢复 API、事务回滚和往返测试。`PLAN.md` 写的 Session 007 早于现有 Session 008，这里按真实时间顺延。
- 基线：`.venv/Scripts/python.exe -m pytest -q` → `121 passed, 1 warning in 2.39s`。第一次直接运行在测试结束后清理全局 `%TEMP%` 的无权访问链接时退出；用例本身全部执行完，改用仓库内临时目录后取得有效退出码。`check.ps1` 的旧仓库根定位 bug 仍存在，本轮按标准命令直接验证。
- 改了哪几个文件、每处为什么这么改：

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/db.py`（新增） | 提供 engine、`SessionLocal`、请求 session provider；SQLite 每个连接执行 `PRAGMA foreign_keys=ON`；引擎构造提成 `create_db_engine()` 便于验证 | 不让每个端点重复造引擎，并确保 ORM 声明的级联删除在 SQLite 真正生效 |
| `app/dependencies.py` | 新增 `get_db_session` 包装 | FastAPI 的会话生命周期从持久化工厂隔离，测试可覆盖依赖 |
| `app/services/story_store.py`（新增） | 集中完成 `StoryBlueprint` 与 ORM 聚合树双向转换；`save_blueprint` 单事务写整棵树并追加一条 `story_created`；`load_blueprint` 逐字段恢复；新增摘要分页查询 | 转换只留一处，API 不碰 Pydantic/ORM 映射；保存中途失败整棵故事回滚 |
| `app/schemas/stories.py`（新增） | 新增创建、摘要、详情、列表响应契约 | 生成态 Schema 保持原样，持久化 API 的公开契约独立演进 |
| `app/api/stories.py`（新增） | 新增 `POST /api/stories`、`GET /api/stories`、`GET /api/stories/{public_id}`；沿用 M1 的上游错误语义；不存在返回 404/40401 | 完成生成后落库、按公开 UUID 恢复和只返回摘要的分页列表 |
| `app/main.py` | 挂载 stories router | 新端点可被实际应用访问 |
| `tests/test_stories_api.py`（新增） | 16 条测试覆盖 SQLite 外键、整树往返、真实行数、事务中途失败回滚、重复保存、非法子实体、3 个 API、分页、404、错误映射和 OpenAPI | 把计划要求的正常路径与失败路径都变成可重复证据 |
| `docs/harness/progress.md` | 本段记录与最新测试数字 | 跨会话状态必须与验证事实一致 |

- 往返逐字段证据：`restored.model_dump() == blueprint.model_dump()` 通过；另外显式核对了标题/简介/类型/主题/集数、2 个角色、2 个指标、3 集及每集 2 个选择、3 个结局，以及 `character_ids`、`effects`、`conditions` 的跨模型键恢复。
- 落库行数证据：保存一个 3 集故事后，`stories=1, characters=2, metrics=2, episodes=3, choices=6, endings=3, story_state_changes=1`。
- 事务回滚证据：通过 SQLAlchemy `after_flush_postexec` 在完整故事树已执行插入后强制抛错；新会话逐表计数，7 张业务表全部为 0。
- 重复保存策略：同一个 blueprint 保存两次创建两个不同 `public_id` 的独立 story，子实体和 `story_created` 记录各写一份。理由：本批没有显式“覆盖已有存档”的版本语义；默认覆盖会静默销毁历史，默认冲突又无法从无身份蓝图判断是否为同一用户意图。生成动作每次产生新存档语义最清楚。
- 跑过的验证和结果（真实数字）：
  - 新增测试单跑：`16 passed, 1 warning in 0.90s`
  - 全量回归：`137 passed, 1 warning in 2.90s`
  - `.venv/Scripts/python.exe -m compileall -q app tests` → 通过
  - `git diff --check` → 无空白错误（仅 Windows 换行提示）
- 约束遵守情况：
  - 未改 `app/api/story_plans.py`、`app/schemas/story_blueprint.py`、`app/services/blueprint_validator.py`。
  - 未改任何已有测试预期；只新增 `tests/test_stories_api.py`。
  - 测试使用内存 SQLite，不污染 `scenechoice.db`。
  - 未执行 `git add` / `git commit` / `git push`。
  - 未推进 `sc-m1-03`，M1 阶段门仍 blocked。
- 已知遗留风险：
  - 外部传入的非法蓝图会在写入前由 `BlueprintValidator` 拒绝；若数据库文件被手工篡改，恢复时可能因 JSON 形状不符直接报内部错误，本批没有损坏存档修复策略。
  - 列表按 `created_at DESC, id DESC` 排序；本批只做 offset/limit，没有游标分页和并发快照保证。
  - POST 是生成接口而不是幂等重放接口；客户端超时后重试可能留下两个独立存档。
  - story store 的整树保存已测量为测试规模可用，尚无大批量/长期压力数据。
- 下一步最佳动作：本人 review 新增数据层、API 与 16 条测试后决定是否提交；之后按第 3 批实现状态变化写入与玩家推进。

### Session 008

- 日期：2026-11-15
- 本轮目标（一句话）：按 `PLAN.md` 落 M2 第 1 批的数据层骨架——六个领域实体 + 状态变化表 + Alembic 首次迁移，不碰 Repository/Service/API。
- 基线：`.venv/Scripts/python.exe -m pytest -q` → `121 passed, 1 warning in 3.20s`
- 改了哪几个文件、每处为什么这么改：

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/config.py` | 新增 `database_url`（`SCENECHOICE_DATABASE_URL`，默认 `sqlite:///./scenechoice.db`） | 迁移与应用必须共用同一个连接串来源；硬编码 URL 会让 env、测试、部署三处各说各话 |
| `app/models/base.py`（新增） | `Base`、约束命名规范、UTC 时间函数 | 持久化层的根；命名规范让 SQLite batch 迁移能稳定引用约束；时间统一 UTC |
| `app/models/enums.py`（新增） | 故事/剧集状态、结局类别、状态变化来源与事件词汇 | 值存字符串 + CHECK（SQLite 无原生 enum）；把词汇集中一处，服务层不再抄字面量 |
| `app/models/story.py`、`character.py`、`metric.py`、`episode.py`、`choice.py`、`ending.py`（新增） | 六张实体表：内部自增 PK + 业务键、外键与级联、CHECK、JSON 列 | 生成态的 Pydantic 模型没有身份、当前状态和时间线，不能直接当 ORM；字段映射差异写在 `app/models/__init__.py` |
| `app/models/state_change.py`（新增） | 追加式状态变化表，`(story_id, sequence)` 唯一 | 吸收点②的载体；本批只建结构，写入器留到第 3 批 |
| `app/models/__init__.py`（新增） | 生成态→持久化态映射、ID 策略、级联边界、运维注意事项 | 设计理由必须和模型放在一起，避免下一批靠猜 |
| `requirements.txt` | 加 `sqlalchemy>=2.1,<2.2`、`alembic>=1.20,<2.0`（按本轮实际验证的 2.1.8 / 1.20.1 对齐） | 依赖要可复现；上一轮暂写的 `<2.1` 与本机实际版本不符，验证后按真实版本收紧 |
| `alembic.ini`、`alembic/env.py`、`alembic/script.py.mako`（新增） | Alembic 入口；URL 从 `Settings` 读；SQLite 打开 batch 模式 | 迁移入口只能有一个 DB URL 来源；SQLite 后续 ALTER 需要 batch |
| `alembic/versions/20261115_0001_initial_domain.py`（新增） | 建 7 张表 + 索引/唯一/CHECK/外键 | 初始骨架，字段与模型逐列对齐 |
| `.gitignore` | 忽略 `*.db` 及 journal/wal/shm | 本地存档不入仓 |
| `docs/harness/progress.md` | 本段记录 | 跨会话状态层 |

- 职责边界说明（为什么不能只改一层）：
  - `app/schemas/` 继续只负责"模型生成的形状"，`app/services/blueprint_validator.py` 继续只负责跨字段业务规则。新 ORM 层不复制十条规则，只保留数据库能局部保证的不变量（外键、唯一、`0..100`、`1..5`、状态取值）。理由：M1 反复修的就是"同一规则写两处会跑偏"。
  - 持久化层新增的是"活下来"所需的东西：代理键、`public_id`、状态、时间戳、`current_value`、状态变化表。生成态没有身份和当前状态，故不能直接当 ORM。
  - API/Service/Repository 本批一律不写；引擎/会话也留到第 2 批，避免本批顺手做出事务语义。
- 跑过的验证和结果（真实数字）：
  - 全量：`.venv/Scripts/python.exe -m pytest -q` → `121 passed, 1 warning in 2.53s`（补跑运行时验证后复跑）
  - 新增 Python 文件字节编译：12 个文件（模型包 + Alembic 入口 + 迁移）无语法错误
  - 静态一致性：模型 `__tablename__` 与迁移 `create_table` 同为 7 张表；66 列的类型与可空性逐列一致；唯一约束 0 差异、CHECK 0 差异、外键目标与 `ON DELETE CASCADE` 语义一致
  - 依赖版本：SQLAlchemy 2.1.8、Alembic 1.20.1（负责人批准后已装进 `.venv`）
  - 从零迁移（临时 SQLite，跑完即删）：
    `INFO  [alembic.runtime.migration] Running upgrade  -> 20261115_0001, M2 batch 1: six domain entities plus the state-change log.`
    迁移后 `alembic_version` = `20261115_0001`；业务表 7 张：`characters, choices, endings, episodes, metrics, stories, story_state_changes`（另有 1 张 `alembic_version` 记账表）。
  - 模型/迁移一致性：`alembic check` → `No new upgrade operations detected.`（项目库与临时新库各跑一次，均为无差异）
  - 项目根 `scenechoice.db` 已由 `alembic upgrade head` 实际创建（`.gitignore` 已覆盖）。
  - 命令入口说明：本会话的 Bash 允许列表没有 `python -m alembic`，运行时改用同一入口 `alembic.config.main(argv=["upgrade", "head"])` / `main(argv=["check"])` 在已批准的 Python 通道执行；行为与 CLI 等价。
- 约束遵守情况：
  - 未改 `app/schemas/story_blueprint.py`、`app/services/blueprint_validator.py`、`app/api/story_plans.py`。
  - 未写 Repository/Service/API/事务/存档恢复逻辑；未新增测试（PLAN 明确把测试放到第 2、3 批）。
  - 未执行 `git add` / `git commit` / `git push`。
  - 本批按负责人本轮明确指令启动 M2；`sc-m1-04` 阶段门仍 blocked，状态未改。
- 已知遗留风险：
  - JSON 里的 `metric_key` / `character_keys` 没有数据库级外键；导入层必须校验，否则会把悬空引用写进存档。
  - SQLite 默认每个连接关闭外键；第 2 批的引擎必须 `PRAGMA foreign_keys=ON`，否则声明了 `ON DELETE CASCADE` 也不会级联。
  - `sqlite:///./scenechoice.db` 相对进程工作目录；从别处启动会把库建到别处。
  - SQLite 读回的时间是 naive；写入统一 UTC，读取方必须按 UTC 解释。
  - 状态变化表没有写入器、没有事务边界；本批只是结构。
  - `docs/ARCHITECTURE.md` 的"M2 未开始"和 `docs/generated/db-schema.md` 的"M1 无数据库"已过时；运行时验证已通过，可在下一次改文档时更新（本批范围不含这两份）。
  - requirements 仍是版本区间（`sqlalchemy>=2.1,<2.2`、`alembic>=1.20,<2.0`），不是精确补丁号锁定；本轮验证的是 2.1.8 / 1.20.1。
  - 本轮没有在 SQLAlchemy 2.0.x 上验证；如果将来降回 2.0 系列，需要重跑 `alembic check`。
- 下一步最佳动作：本人 review 本轮数据层与迁移后决定是否提交；之后进入第 2 批（engine/session 工厂、`PRAGMA foreign_keys=ON`、Repository），并按 PLAN 补第 2 批测试。M1 阶段门仍卡 `sc-m1-03`，本批未推进。

### Session 007

- 日期：2026-11-15
- 本轮目标（一句话）：把「哪些上游状态码算可重试」这份知识从两处硬编码收敛成单一事实来源，让客户端「要不要再试」和 API「报什么码」不可能各自跑偏。
- 基线：`.venv/Scripts/python.exe -m pytest -q` → `120 passed, 1 warning`（上一轮 402/1xx/3xx/200 收工时的数字）
- 改了哪几个文件、每处为什么这么改：

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/clients/deepseek.py` | 新增 `_RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 429})` 与纯函数 `is_retryable_status()`（408/429 或 >=500）；`complete()` 里的 `retryable = ...` 改为调用它 | 放客户端模块，因为这是「上游 HTTP 错误语义」，而且 API 层本来就从这个模块 import 异常类型，契约已经有一个现成的家，不必为一行判断新造一层。也刻意没有把「要不要重试」和「报什么业务码」合成一个函数：PLAN 里写明那是两个不同的问题 |
| `app/api/story_plans.py` | import `is_retryable_status`；4xx 分支的 `exc.status_code not in {408, 429}` 改成 `not is_retryable_status(exc.status_code)` | API 层不再维护第二份状态码清单。以后要支持 425、409 之类只改一个地方，不会出现「客户端认为可重试、API 却报请求错误」这种两层各自都看着对的错位 |
| `tests/test_retryable_status_source.py`（新增） | 参数化扫 400..599：客户端侧用 `MockTransport` 真跑 `DeepSeekClient.complete()` 取 `retryable`，断言它与 `is_retryable_status(s)` 一致；API 侧用失败 planner 真打 `/api/story-plans/preview`，断言落 `50201` 还是 `50202` 也来自同一判定；跳过 401/402/403（这三个在 4xx 分支之前已被业务规则截走） | 这就是 PLAN 要的「只改一处要能变红」的网：任何一层留着硬编码清单，这条测试立刻对不上 |
| `PLAN.md` | 从 P2-2 任务书换成这次重构的任务书（重复在哪、做法要求、约束、收工要输出） | 本轮按「先立 PLAN 再动手」的流程走。代价是 P2-2 的原方案表被覆盖，只剩本文件 Session 005 里的归档版（见遗留风险） |
| `docs/harness/progress.md` | 本段记录；顶部「标准验证路径」的数字从 120 改为 121 | 状态层要跟实际验证结果对得上 |

- 跑过的验证和结果（真实数字）：
  - 全量：`.venv/Scripts/python.exe -m pytest -q` → `121 passed, 1 warning in 2.76s`；`--collect-only` → `121 tests collected in 0.39s`（比上一轮净增 1 条，就是新增的一致性测试）
  - 新增测试单跑：`pytest -q tests/test_retryable_status_source.py` → `1 passed, 1 warning in 1.52s`
  - 「行为没变」的对照（跑出来的，不是静态看的）：用旧表达式 `status in {408, 429} or status >= 500` 与新函数 `is_retryable_status` 在 100..599 全 500 个状态上逐个比对 → `compared: 500 / mismatches: [] / retryable count: 102`（408、429 加 500..599 共 102 个，集合一个没变）
  - 既有 API 状态矩阵没被改坏：`pytest -q tests/test_story_plans_api.py tests/test_deepseek_client.py` → `37 passed, 1 warning in 0.78s`（含上一轮 401/403/408/429/500/422/402/100/302/200 全部用例）
  - 代码里确实只剩一份清单：`grep -rn "408\|429\|is_retryable_status" app/`（排除 .pyc）只命中 `deepseek.py:13/16/106` 与 `story_plans.py:3/72`
- 约束遵守情况：
  - 只新增测试，未修改任何已有测试的预期结果（两个测试文件都只有新增与 import 调整）。
  - 未改 `blueprint_validator.py`、Schema、异常体系结构，也未动 feature_list 状态与 M1 阶段门。
  - 未执行 `git add` / `git commit` / `git push`。
- 已知遗留风险：
  - 两轮改动都还在工作区：HEAD 仍是 `de032eb`，`git status` 为 6 个改动文件 + 2 个未跟踪项（`.claude/`、`tests/test_retryable_status_source.py`）。`121 passed` 只存在于工作区，提交前别当已入库事实。
  - `.claude/`（`settings.local.json` 及其 `.bak`）没被 `.gitignore` 覆盖，将来 `git add -A` 会把本机工具配置带进仓。
  - 一致性测试只扫 400..599，没覆盖 1xx/3xx；1xx/3xx 走 `story_plans.py` 的另一条分支（<400 → 502/50204），行为有上一轮测试钉住，但「只改一处会变红」的保护不覆盖它。
  - 一致性测试对每个状态都真打一次 API（200 次），单跑约 1.5s，是全套里最慢的一条；状态列表或中间件变重时会继续拉长。
  - 402 仍映射 503/50303（欠费不等于服务不可用），是上一轮已定方案，本轮没动；语义上仍留出被调用方当作「稍后重试」的空间。
  - 404 仍只有客户端断言，API 层状态矩阵里没有 404 用例（继承上一轮遗留）。
  - `docs/SECURITY.md`、`docs/RELIABILITY.md` 错误码表仍未收录 400/50202、50204、50303，文档落后于实现。
  - 未跑 `./docs/harness/init.sh` 一键体检（它会装依赖，无人值守时不想动环境），本轮证据一律来自直接测试命令；`check.ps1` 的仓库根定位 bug 依旧在。
  - M1 阶段门仍卡 `sc-m1-03` 个人掌握验收，本轮没有推进它。
- 下一步最佳动作：本人 review 这 6 个改动文件后决定是否提交；之后把 404 与 1xx/3xx 补进同一张 API 状态矩阵，并按同一口径同步 SECURITY/RELIABILITY 的错误码表。

### Session 006

- 日期：2026-11-15
- 本轮目标（一句话）：补齐 DeepSeek 上游 402、1xx/3xx 与 200 畸形正文三条边界的错误分类和 API 层证据。
- 基线：`.venv/Scripts/python.exe -m pytest -q` → `113 passed, 1 warning`
- 改了哪几个文件、每处为什么这么改：

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/api/story_plans.py` | 402 单独映射为 503 + `50303`，文案为 `story model account has insufficient balance`；非 None 且小于 400 的状态映射为 502 + `50204`，文案为 `story model returned an unexpected protocol status`；保留 401/403、408/429、5xx 原映射 | 欠费要人充值，不属于请求写错；1xx/3xx 是上游协议异常，也不等于模型临时故障。OpenAPI 的 502/503 描述同步写出 `50204`/`50303`，让调用方能在契约层区分 |
| `app/clients/deepseek.py` | 200 正文畸形产生的 `DeepSeekClientError` 保留 HTTP 状态 `200`，仍为 `retryable=True` | API 原来只看到 `status_code=None`，会把重试耗尽的畸形正文误报为 502/50201；保留状态后才能与网络超时区分 |
| `app/api/story_plans.py` | 重试耗尽后的 `status_code=200` 映射为 422 + `42201` | 按本轮方案，200 成功状态配畸形正文属于故事生成失败，不是模型当前不可用 |
| `tests/test_story_plans_api.py` | 新增 402、1xx/3xx、200 畸形正文、OpenAPI 区分错误码测试 | 1xx/3xx 用真实 `DeepSeekClient` + `MockTransport` 走完整链路；200 畸形正文断言 `content` 非字符串、缺 `choices` 两种输入都尝试 3 次后返回 422/42201 |
| `tests/test_deepseek_client.py` | 新增 200 畸形正文保留状态、仍可重试的单元测试 | 防止以后再次丢失区分畸形正文与传输失败所需的信息 |
| `docs/harness/progress.md` | 本段记录 | 保存跨会话的验证事实和下一步 |

- 跑过的验证和结果（真实数字）：
  - 基线：`113 passed, 1 warning`
  - 402/1xx/3xx 期望测试：`2 failed, 113 passed`（402 当前为 400/50202，3xx 当前为 502/50201）
  - 映射实现后：`115 passed, 1 warning`
  - 200 畸形正文端到端测试：`2 failed, 115 passed`（证明当前错误落到 502/50201）
  - 客户单状态元数据测试：`3 failed, 115 passed`（200 状态尚未保留）
  - 客户端修复后：`2 failed, 116 passed`（只剩 API 映射）
  - API 修复后：`118 passed, 1 warning`
  - OpenAPI 契约测试补充后：`119 passed, 1 warning`
  - 1xx/3xx 扩展为真实上游参数化后：`120 passed, 1 warning`
- 约束遵守情况：
  - 未修改已有测试的预期结果，只新增测试。
  - 未修改 401/403、408/429、5xx 的既有映射。
  - 未执行 `git add` / `git commit` / `git push`。
  - 未动 `blueprint_validator.py`、Schema 或异常体系结构。
- 环境说明：
  - `docs/harness/check.ps1` 的仓库根定位 bug 仍存在，本轮直接用规定测试命令验证。
  - 全局 pytest 临时目录仍有不可访问遗留链接；测试时将 `TEMP`/`TMP` 指向 `.pytest-cache/harness-tmp`，不改项目代码。
- 下一步最佳动作：本人 review 本轮 402、1xx/3xx、200 畸形正文映射与新增测试；M1 阶段门仍等待 `sc-m1-03` 个人掌握验收。

### Session 005

- 日期：2026-11-14（2026-11-15 归档核对）
- 本轮目标（一句话）：修复巡检报告 P2-2 —— DeepSeek 返回的永久 4xx 不再被映射成「模型临时不可用 502」，免得调用方对着注定失败的请求反复重试。
- 归档时的仓库状态：改动已提交为 `de032eb`，`git status` 干净、`git diff --stat` 为空（下面列的是这次提交实际动过的 6 个文件）
- 改了哪几个文件、每处为什么这么改：

| 文件 | 改了什么 | 为什么这么改 |
|---|---|---|
| `app/api/story_plans.py` | 新增 4xx 分支：除 401/403/408/429 外，其余 4xx 返回 400 + `50202`，文案改成 `story model rejected the request`；OpenAPI 补一条 400 响应契约 | 请求本身错了，重试一万次结果一样，不该报「临时不可用」。401/403 必须放在这个分支之前（凭证被拒要人去换 key → 503/50302），408/429 与 5xx、`status_code=None` 继续走 502/50201（真临时）。补 OpenAPI 是让调用方在契约里就能看到 400 |
| `tests/test_story_plans_api.py` | 新增一条 400 红灯用例；新增状态矩阵（401/403→503/50302，408/429/500→502/50201，422→400/50202）；新增 OpenAPI 契约用例 | 先让它红着当证据，证明改动真生效；矩阵把「没改坏 401/403/408/429/5xx 原有行为」钉成断言，而不是嘴上说没改坏 |
| `tests/test_deepseek_client.py` | 断言 400/404/422 三个状态都是 `retryable=False` | 客户端本来就不重试 4xx，此测试是防止后人把全部 4xx 改成可重试的回归网 |
| `.gitignore` | 忽略 `node_modules/`、`package-lock.json` | 本地 TDD 守卫工具的 Node 依赖不该进仓，不影响 Python 工程 |
| `PLAN.md` | 换成 P2-2 的任务书：错误码方案表、约束、子任务队列、不要做的事 | 本轮按「先定错误码表再实现」的方式做，方案表定稿后代码只是照着落 |
| `docs/harness/progress.md` | 本段记录 | 跨会话状态层，收工必写 |

- 过程中踩到并修掉的两处：
  - 400 分支初版范围写宽了，408/429 也被卷进 400；状态矩阵立刻抓出来（`2 failed, 107 passed`），改成显式排除后才转绿。
  - 首次跑 `./docs/harness/init.sh` 因全局 uv 缓存锁不可访问而失败，换成任务专属可写缓存后重跑通过。
- 跑过的验证和结果（真实数字）：
  - 基线：`102 passed`
  - 400 红灯：`1 failed, 102 passed`
  - 范围写宽时的中间态：`2 failed, 107 passed`
  - 全量：`.venv/Scripts/python.exe -m pytest -q` → `113 passed, 1 warning in 1.52s`（基线 102，净增 11 条用例；`--collect-only` 同为 113）
  - 归档核对复跑（2026-11-15）：`113 passed, 1 warning in 1.44s`
  - 独立评审轮：结论「通过」，同时点出下面几条残余风险，本轮按其结论收口
  - 没跑成的一轮：边界验算（「验算错误码映射边界」）因本机缺 DeepSeek 凭证没执行，所以边界结论目前只有评审的静态检查，没有独立的运行时验算
- 已知遗留风险：
  - 「哪些 4xx 算临时」这份知识写了两处：`app/api/story_plans.py:47` 的 `{408, 429}` 与 `app/clients/deepseek.py:92` 的 `retryable` 判定必须同步改，将来加入 425 之类会出现「客户端认为可重试、API 却报 400」的错位。
  - 404 只有客户端测试覆盖，API 层状态矩阵还没有 404 用例（方案点名 400/404/422 三态，矩阵只覆盖了其中两态）。
  - `docs/SECURITY.md`、`docs/RELIABILITY.md` 的错误码表尚未收录 400/50202，文档与实现暂时不同步。
  - 409/499 也落进 400/50202，499（客户端断开）语义偏临时；按已定方案接受，仅记录。
  - 3xx 不经过这条映射（httpx 默认不跟随重定向，3xx 走 JSON 解析路径），属既有行为，非本轮引入。
  - 未修改已有测试预期、feature_list 状态或 M1 阶段门；M1 阶段门仍卡 `sc-m1-03` 个人掌握验收。
- 下一步最佳动作：把 404 补进 API 层状态矩阵、或按同一口径同步 SECURITY/RELIABILITY 的错误码表；M1 阶段门继续等待个人掌握验收

### Session 004

- 日期：2026-11-14
- 本轮目标：修复规则 4 可被 `delta: 0` 假效果绕过的 P2-1 缺陷
- 已完成：
  - 基线 `98 passed`；新增反例测试后先确认旧逻辑不报规则 4
  - 将反例断言改为必须报错，取得 `1 failed, 98 passed` 的红灯证据
  - 规则 4 比较前剔除 `delta == 0` 的效果，只比较实际状态变化
  - 任一侧没有非零效果时不重复报规则 4，由规则 6 分别报告该选择缺少非零变化
  - 新增 4 条测试：零效果伪装相同结果、方向相反仍合法、双方夹带零效果仍相同、单侧全零只报规则 6
  - 修正验收审计中规则 4 的表述：仅比较 effects，注明 intent 字段当前未被使用
  - 未修改已有测试预期、Schema、错误码映射、规则 10、feature_list 状态或 M1 阶段门
- 运行过的验证：
  - 基线：`.venv/Scripts/python.exe -m pytest -q` → 98 passed, 1 warning
  - 反例旧行为：99 passed（证明新增测试复现漏报）
  - 红灯：1 failed, 98 passed（命中零效果伪装相同结果）
  - 全量验证：`.venv/Scripts/python.exe -m pytest -q` → 102 passed, 1 warning in 1.71s
- 环境说明：全局 `%TEMP%` 中仍有不可访问的 pytest 遗留链接；本轮将 TEMP/TMP 指向项目内 `.pytest-tmp` 后运行同一测试命令
- 已知风险：无新增业务风险；系统临时目录遗留链接仍需本机环境处理
- 下一步最佳动作：负责人 review 本次 validator 改动与新增测试；M1 阶段门仍等待 `sc-m1-03` 个人掌握验收

### Session 003

- 日期：2026-11-14
- 本轮目标：修复规则 9 的同质结局漏洞，并收紧 low/high 结局的语义区间
- 已完成：
  - 基线 `94 passed`；先复现三个不同 category 使用相同条件时校验无报错
  - 新增大小写、顺序无关的结局条件签名（metric_id + operator + value），拒绝不同 category 共用同一签名
  - low/high 结局现在必须分别允许到达 0..49 / 50..100 的状态带；50 是临时中点边界，已在代码注释注明“阈值待产品确认”
  - 新增 4 条回归测试：同质签名报错、low 仅高值报错、high 仅低值报错、合法差异条件通过
  - 未修改既有测试预期、Schema、feature_list 状态或 M1 阶段门
- 运行过的验证：
  - 缺陷复现：`.venv/Scripts/python.exe -m pytest -q tests/test_blueprint_validator.py::test_different_categories_cannot_share_identical_conditions --basetemp .pytest_cache\\tdd-reproduce` → 1 passed（证明旧行为漏报）
  - 红灯：`tests/test_blueprint_validator.py` → 3 failed, 27 passed（分别击中 P1-A、low 区间、high 区间）
  - 针对性验证：`tests/test_blueprint_validator.py` → 30 passed
  - 全量验证：`.venv/Scripts/python.exe -m pytest -q` → 98 passed, 1 warning in 2.18s
  - 最终体检：`./docs/harness/init.sh` → 依赖同步、98 passed, 1 warning in 2.08s、`compileall app` 通过
- 环境说明：全局 `%TEMP%` 中有不可访问的 pytest 遗留链接，本轮验证将 TEMP/TMP/PYTEST_DEBUG_TEMPROOT 指向项目内 `.pytest_cache/harness-tmp`
- 已知风险：50 中点只是临时保守阈值；产品定义 low/high 分界后需复核
- 另发现：`docs/harness/check.ps1` 仍按上溯两级找仓库根，会把 `docs/` 当成根目录；本次未改这个无关问题，最终验证改用 `init.sh`
- 下一步最佳动作：负责人 review 本次 validator 改动；M1 阶段门仍需完成 `sc-m1-03` 个人掌握验收

### Session 002

- 日期：2026-11-13
- 本轮目标：按 repo-template 骨架把规范文件归入 `docs/`，根目录只留三个入口
- 已完成：
  - 根目录只保留 `AGENTS.md` / `CLAUDE.md` / `README.md`
  - harness 状态文件迁入 `docs/harness/`（progress / feature_list / init.sh / check.ps1 / session-handoff / clean-state-checklist / evaluator-rubric）
  - `quality-document.md` 迁为 `docs/quality/QUALITY_SCORE.md`
  - 新建 `docs/ARCHITECTURE.md` / `DESIGN.md` / `PLANS.md` / `PRODUCT_SENSE.md` / `FRONTEND.md` / `RELIABILITY.md` / `SECURITY.md`
  - 新建 `docs/design-docs/`、`docs/exec-plans/`、`docs/generated/`、`docs/product-specs/`、`docs/references/`
  - `AGENTS.md` 增加 Documentation Routing 路由表，更新所有路径
  - `init.sh` / `check.ps1` 改为从 `docs/harness/` 上溯两级定位仓库根
- 运行过的验证：`bash docs/harness/init.sh` → 94 passed、退出码 0；根目录仅剩 3 个 `.md`
- 已知风险：`FRONTEND.md`、`generated/db-schema.md`、`references/nixpacks` 当前不适用，已标注触发条件；`quality.md` 旧记录里的路径是历史事实，未改

### Session 001

- 日期：2026-11-12
- 本轮目标：把 harness 规范（AGENTS / feature_list / progress / init.sh）铺进本项目，补上"状态层"
- 已完成：
  - 装 `init.sh`（Python/FastAPI 版，自动找 `.venv`）
  - 建 `feature_list.json`：4 条真实功能（2 passing / 1 not_started / 1 blocked）
  - 建本文件，填当前已验证状态五段
  - 在 `AGENTS.md` 加 "Session Startup & Handoff" 一节，要求 agent 开工读本文件、收工更新两份状态
  - 补 `session-handoff.md` / `clean-state-checklist.md` / `evaluator-rubric.md` 三份空白模板
  - 补 `check.ps1`（一命令跑 pytest + compileall + ruff，缺 ruff 自动跳过）；`session-handoff.md` 已填真实内容
  - 清理根目录 12 个中断安装留下的空目录（`pip-build-tracker-*` / `pip-ephem-wheel-cache-*` / `pip-install-*`）
  - 修正 `AGENTS.md` 两处过时信息（学习任务已完成、CI 文件名 `.github/workflows/ci.yml`）
  - 按本项目真实领域与架构层重写 `quality-document.md`（不是课程示例那套 Electron 表）
- 运行过的验证：
  - `.venv/Scripts/python.exe -m pytest -q` → `94 passed, 1 warning in 2.34s`
  - `./init.sh` → 依赖同步 + 94 passed + 打印启动命令，退出码 0
- 已记录证据：见 `feature_list.json` 的 `evidence` 字段
- 提交记录：未提交（工作区改动待本人确认）
- 更新过的文件或工件：`init.sh`、`feature_list.json`、`progress.md`、`AGENTS.md`
- 已知风险或未解决问题：
  - `.venv` 之前是半装状态（pluggy 缺 `__init__.py`、pytest 缺 `_pytest.config`、pydantic 缺 `Field`），已用 `uv pip install --reinstall -r requirements.txt` 修好。**没有 pip 的 venv 里别用 `python -m pip` 修包**，要用 uv。
  - `pip-install-*` / `pip-build-tracker-*` / `pip-ephem-wheel-cache-*` 等空目录、`pytest-of-Administrator`（pytest 临时目录）、`.venv.new/` 均已删除，根目录干净。
  - `AGENTS.md` 第 27 行的"current task is adding a validator rule that rejects duplicate character_ids"曾过时（`a6b08cf` 已做），本轮已改为"该规则已完成"，指向学习清单下一项。
- 下一步最佳动作：做 `sc-m1-03`——打开 `docs/learning/scenechoice-m1-learning-review.md`，按 6 项逐条自查勾选，再脱稿讲一遍 M1 数据流
