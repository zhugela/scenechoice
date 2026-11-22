# PLAN — M2 第 12 批：SQLite 并发与持久化设置（WAL + busy_timeout）

> 来源：`docs/harness/reviews/latest.md` 的 P3「SQLite 只开了 foreign_keys，没有 WAL / busy_timeout」
> 与 M2 评审第 6 问（SQLite 坑）。本批**不加任何新用户可见行为**。
> 基线：`0aaa272`，`204 passed`。

## 一、现状事实

| 事实 | 证据 |
|---|---|
| 连接级只设了 `PRAGMA foreign_keys=ON` | `app/db.py:17-22` |
| 没有 `busy_timeout` | `grep -rn "busy_timeout" app/` 零命中 |
| 没有 `journal_mode=WAL` | `grep -rn "journal_mode\|WAL" app/` 零命中 |
| 默认 rollback journal 下多写会 `database is locked`，SQLAlchemy 的默认超时只能算缓解 | 评审 P3 原文 |

## 二、本批做什么

### U1 连接级 `busy_timeout`

- `app/db.py` 的连接监听里，SQLite 连接除了 `foreign_keys` 再加 `PRAGMA busy_timeout = <常量>`
- 常量写清「为什么是这个值」：它管的是**等锁多久**才报 `database is locked`，和 SQLAlchemy 的
  `connect_args` 超时是两回事；取一个「比一次事务长、又不至于让请求挂死」的值即可，写进常量注释。

### U2 库级 `journal_mode=WAL`

- 引擎创建后对 SQLite 库执行一次 `PRAGMA journal_mode=WAL`（幂等：已经是 WAL 再设一次无害）。
- **必须只对文件库做**：`:memory:` 库设 WAL 会返回 `memory`，不是错误，但也没意义 —— 判掉，并把理由写进注释。
- 若返回不是 `wal`，**不要让应用起不来**：记一条 warning 日志说明「没切到 WAL，可能是有别的连接占着」，
  继续跑（一个开发机上的日志行，比启动失败更有用）。

### U3 测试（3 条）

1. 文件库：`create_db_engine(url)` 之后，新连接的 `PRAGMA journal_mode` 读回 `wal`，`PRAGMA busy_timeout` 读回常量值。
2. 内存库（`sqlite://`）：不报错、不尝试切 WAL（断言 `journal_mode` 仍是 `memory`）。
3. 连接监听对新开的每个连接都生效（连开两个连接各读一次，值都在）。

### U4 文档

`docs/RELIABILITY.md` 加一节「SQLite 并发假设」，写清：
- WAL 下读写不互相阻塞，但**写仍然是单写者**；多进程同时写会排队等 `busy_timeout`
- WAL 会产生 `-wal` / `-shm` 文件，已在 `.gitignore` 覆盖，备份时要一起拷
- 这一节的存在意义：M3 上线前若改多进程部署，必须回来重读

## 三、禁改清单

- 任何对外行为（状态码、业务码、message、响应字段、API 契约）
- `app/schemas/*`、`app/services/*`、`app/models/*`、`alembic/*`、`requirements.txt`
- 任何已有测试的预期结果
- 各 feature 状态

## 四、验收标准

1. `pytest -q` ≥ 207（3 条新增），已有用例零改动。
2. 变异测试两条：把 `busy_timeout` 的常量改成 0 → 用例 1 变红；删掉 WAL 调用 → 用例 1 变红。
3. `grep -rn "busy_timeout\|journal_mode" app/` 只命中 `app/db.py`。
