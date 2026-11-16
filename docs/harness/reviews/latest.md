# SceneChoice 评审 — M2 架构评审（模型 + 事务 + 存档/恢复 API）

评审对象：HEAD 上的 `77df366`（领域模型 + ORM + 迁移）与 `bf7d736`（Repository + 存档/恢复 API）。工作区未提交改动只有 `PLAN.md` 与 `docs/harness/progress.md`，没有业务代码；本轮按事件「M2 架构评审」和 `PLAN.md` 的七个问题评审这两批提交。只读评审，未改动源文件、未 add/commit/push。

Review verdict: CHANGES REQUIRED

## 逐条回答本轮清单

1) **需求对齐** — 第 2 批计划里的 Repository、三端点、单事务保存、重复保存策略、往返测试都做了，`preview` 未被改动（`git log` 确认 `app/api/story_plans.py`、`app/clients/deepseek.py` 自 `ce7e293` 后未变）。但对齐不完整：M2 目标③「存档/恢复体验」只交付了“生成态 bluePrint 导出/导入”，玩法进度（`Metric.current_value`、`Episode.status`、状态变化日志）写进去却读不出来，见 P1 第一条。
2) **边界遗漏** — 映射分支本身没有漏：3xx→50204、200 畸形→42201、401/403→50302、402→50303、409/499→永久 4xx→400/50202、0/负数→50204、408/429/5xx→50201，代码里都能走通（`app/api/stories.py:30-76`）。漏的是 `/api/stories` 上的测试证明：7 行参数表只覆盖了 401/402/200/400/302/None，见 P2 第四条。499 归为“永久拒绝”是语义上的可讨论点，DeepSeek 正常不会返回 499，本批不按缺陷算。
3) **已有行为** — 401/403/408/429/5xx 的既有映射未被改坏：`app/api/story_plans.py:48-87` 未变，`tests/test_retryable_status_source.py:34-66` 的 400–599 全量循环仍守着 preview；`is_retryable_status` 的集合也没有被改（`app/clients/deepseek.py:13-18`）。风险是 `stories.py` 复制了一份映射，后续只改一侧会漂移，见 P2 第三条。
4) **测试质量** — 强项是真实证据：七张表逐表行数、真实事务回滚（`after_flush_postexec` 强制失败后新会话查 0 行）、`model_dump()` 全量相等、404 精确响应体、OpenAPI 断言。弱项是覆盖率与“复述实现”：新端点的错误表只挑了一部分分支；endings 排序 bug 被工厂数据的 1/2/3 顺序掩盖；savepoint 分支、5 集路径、损坏存档都没测，见 P2 第二/五/六条与 P3 的测试条目。
5) **可维护性** — 清单点名的“哪些状态可重试”确实同源在 `app/clients/deepseek.py`，这点做对了；但同一份“上游错误→HTTP 错误码”的完整契约在 `stories.py` 和 `story_plans.py` 写了两遍（P2 第三条）。另外请求体 schema 重复（P3）、测试里复制了一份 PRAGMA 监听（P3）。

## Findings

- [P1] 「存档/恢复」只恢复了生成态，玩法进度全部丢弃 — `app/services/story_store.py:172-262`、`app/schemas/stories.py:34-36`、`app/api/stories.py:158-173` — `save_blueprint` 写入 `Metric.current_value`（`story_store.py:80`）和 `Episode.status`（`story_store.py:95`），但 `load_blueprint` 只按 `StoryBlueprint` 还原 `initial_value`，这两个字段从不读；`story_state_changes` 只写（`story_store.py:156-167`）没有任何读接口，详情响应里只有 `public_id + blueprint`。玩家推进后按 `public_id` 恢复会回到初始状态，M2 吸收点③实际没有交付；若 M2 以本批收尾，属于验收缺口。建议：补 `GET /api/stories/{public_id}/state`（各 metric 当前值、各 episode 状态、最后 sequence）或在验收文档里把目标③显式降级到第 3 批并写清剩余工作，二者择一，不要再用“已实现存档恢复”表述。

- [P2] `blueprint_version` 只建列不读写，schema 演进后旧存档恢复会变成 500 — `app/models/story.py:71-73`、`app/services/story_store.py:50-59`、`app/services/story_store.py:188-262`、`app/middleware.py:23-31` — 保存时不显式写版本（只吃列默认 1），恢复时也不校验；一旦 `StoryBlueprint` 形状变化，旧存档会在 `StoryBlueprint(...)` 构造处抛 pydantic `ValidationError`，被中间件兜成 500「internal server error」，无法区分“旧版本存档”和“数据损坏”，也没有修复路径。建议：save 时显式落版本，load 时先比版本，不匹配返回受控错误（如 409/422 + 专用 code），并补一条“篡改版本/JSON 形状”的测试；补上之前不要在文档里承诺旧存档仍可解释。

- [P2] 上游错误映射整段复制两份，只有“可重试状态集合”真正同源 — `app/api/stories.py:30-76` vs `app/api/story_plans.py:48-87` — 两个路由的分支链逐条相同；共享的只有 `is_retryable_status`（`app/clients/deepseek.py:13-18`），stories 副本还丢了所有 `from exc` 异常链。后续只改一侧，就会出现“同一个上游错误在预览和落库两个接口返回不同 code”。建议：抽一个 `provider_error_to_app_error(exc) -> AppError` 共用函数（放 clients 或 services 层），两个路由只调用它；把 `test_retryable_status_source.py` 的 400–599 循环扩到 `/api/stories`。

- [P2] 新端点的错误码矩阵测试只覆盖 7 种组合，409/408/429/499/0/负数/5xx 没有断言 — `tests/test_stories_api.py:298-370` — 参数表只有 401/402/200/400/302/None/`StoryPlanningError`；全量 400–599 的循环（`tests/test_retryable_status_source.py:34-66`）只打 preview。于是 `stories.py` 里复制出来的映射被改坏（例如把 408/429 变成 400，或 5xx 不再映射 50201）时 CI 仍然全绿。建议：把 `tests/test_story_plans_api.py:204-232` 的表补上 403/408/429/500，并对 `POST /api/stories` 跑同一组；409/499 若产品上想归为临时失败，需要单独决定，不要默默沿用永久 4xx。

- [P2] endings 回读按 priority 重排，合法 blueprint 的数组顺序会丢 — `app/models/story.py:104-109`、`app/services/story_store.py:244-261` — 关系用 `order_by="Ending.priority"`，而验证器只要求 priority 唯一（`app/services/blueprint_validator.py:142-144`），不要求数组按 priority 升序。因此 `endings=[priority 2,1,3]` 这种合法输入存进去后，`restored.model_dump() != blueprint.model_dump()`，GET 详情与同一故事的 preview 输出顺序不同。当前测试工厂恰好是 1/2/3（`tests/blueprint_factory.py:77-105`），抓不到。建议：像 `Character.position` 一样加 `position` 列并按它排序（需要一次迁移），或在 load 时按保存时的数组位置还原；补一条乱序 priority 的往返测试。

- [P2] `save_blueprint` 的 savepoint 分支完全没有测试 — `app/services/story_store.py:147-150` — 调用方已在事务中时走 `begin_nested()`，这是第 3 批把保存嵌进更大事务的入口；目前只有“独立事务 + 首轮 flush 后抛错”的回滚测试（`tests/test_stories_api.py:156-192`）。如果 savepoint 路径失败时没回滚干净，或外层回滚/提交语义与 docstring 不符，要到第 3 批才暴露。建议：补三条测试：外层事务内保存后外层 rollback → 七张表为 0；外层 commit → 故事落库；savepoint 内失败 → 外层事务仍可继续。

- [P2] 恢复接口把角色 secret 与结局条件原样返回，没有任何归属校验 — `app/api/stories.py:158-173`、`app/models/character.py:52-54`、`app/schemas/stories.py:34-36` — `public_id` 是 UUID，不易猜，但它同时是唯一凭据；拿到链接的人能看到“玩家尚未得知的秘密”和全部结局规则，而模型注释明确说 secret 不应进入玩家可见 payload。M2 没有鉴权，这不是本批引入的回归，但它是 M3 玩家界面的前置决定。建议：先定 `public_id` 的定位（能力链接，禁止写日志、避免 Referer 泄漏），或在做玩家界面前加 ownership 并拆一个不含 secret/conditions 的公开读模型；至少写进验收风险。

- [P3] 生成元信息（模型、尝试次数、token 用量）没有落库 — `app/api/stories.py:121-134`、`app/services/story_planner.py:28-36`、`app/services/story_store.py:156-167` — `create_story` 只把 `result.blueprint` 交给保存，`PlanningResult` 里的 `model/attempts/prompt_tokens/completion_tokens/duration_ms` 全部丢弃，`story_created` 的 `after_state` 只有 `{"status": "ready"}`。事后无法回答这份存档由哪个模型、几次尝试、多少成本生成，也无法复现评测。建议：在 `stories` 加生成元信息列，或把 meta 写进 `story_created` 的 `after_state`。

- [P3] `async def create_story` 里同步跑 SQLAlchemy — `app/api/stories.py:116-134` — 事件循环会被数据库写入（以及 SQLite 锁等待）阻塞，并发请求一起卡；当前单机小规模可接受。建议：`save_blueprint` 用 `run_in_threadpool`/`anyio.to_thread` 包一层，或把路由改成普通 `def`（保留 `planner.plan` 的 await，仅把 DB 段下沉）。

- [P3] 时间戳以无时区形式返回 — `app/models/base.py:32-39`、`app/schemas/stories.py:26-27` — SQLite 读回 naive datetime，FastAPI 序列化后没有 Z/偏移，客户端在非 UTC 时区会解析错；与 `utcnow()` 注释里的“读者按 UTC 处理”契约不一致。建议：`_summary` 里统一 `replace(tzinfo=timezone.utc)` 或加 serializer，测试断言带时区。

- [P3] SQLite 只开了 `foreign_keys`，没有 WAL / busy_timeout — `app/db.py:17-24` — `PLAN.md` 第 6 问里的 WAL、并发写没有处理：默认 rollback journal 下多写会 `database is locked`（SQLAlchemy 默认 5s 超时只算缓解）。建议：连接监听里加 `PRAGMA busy_timeout`，启动时对库执行一次 `PRAGMA journal_mode=WAL`，并在运维文档写清单写者假设。

- [P3] POST 没有幂等键，超时重试会重复计费并留下两份存档 — `app/api/stories.py:93-134` — `progress.md` 已承认；调用方或网关重试会再次调用 LLM 并新建 story，无法判断是否同一意图。建议：接受 `Idempotency-Key` 并做唯一约束；若本批不做，至少把“POST 非幂等”写进对外契约。

- [P3] 列表的 total 与当页是两次查询，offset 分页在并发写入下会漂 — `app/services/story_store.py:265-274` — 新增/删除落在两次查询之间时 total 与 items 对不上，翻页会重复/漏行。建议：M2 可接受，M3 前换 `(created_at, id)` 游标分页，或把快照不一致写进契约。

- [P3] 新增测试的几个盲区：只有 3 集路径；没有损坏存档/旧版本存档的 API 测试；回滚钩子挂在第一次 flush 后（`tests/test_stories_api.py:156-192`），`story_state_changes` 插入失败的回滚没测；测试自己复制了一份 PRAGMA 监听（`tests/test_stories_api.py:53-72`）而不是用 `create_db_engine`，两份监听可能漂移 — 建议：加 5 集往返、损坏 JSON→受控错误、第二次 flush 后失败的用例，fixture 改用 `create_db_engine` + `StaticPool`。

- [P3] 请求体 schema 重复定义 — `app/schemas/stories.py:11-15` vs `app/schemas/story_blueprint.py:79-81` — `CreateStoryRequest` 与 `CreateStoryPlanRequest` 字段、约束完全一样，后续改一处会分叉。建议：让前者继承后者或直接复用，并在 OpenAPI 里保持名字可区分。

- [P3] blueprint id 无长度上限，数据库列是 `String(40)` — `app/schemas/story_blueprint.py:11,19,28` vs `app/models/character.py:43`、`app/models/metric.py:53`、`app/models/ending.py:50` — SQLite 不校验 VARCHAR 长度，所以现在不报错；未来换 Postgres 或做导出校验时，超长 id 会在写入时失败，而 M1 校验阶段放行。建议：给 id/metric_id 加 `max_length=40`（属 M1 schema 变更，另走流程），或在存储层显式拒绝。

- [P3] `story_state_changes` 的 `entity_type` / `event_type` 没有 CHECK 约束 — `app/models/state_change.py:76-78`、`alembic/versions/20261115_0001_initial_domain.py:186-188` — 同表的 `source` 有 CHECK，这两个没有；一次拼写错误会写入无法按枚举查询的事件，破坏回放。建议：补 CHECK（与 `app/models/enums.py:40-54` 对齐），或明确接受应用层枚举并在写入处集中校验。

- [P3] 覆盖缺口里被 PLAN 点名的行：`app/db.py:15` 是非 SQLite 早退（防御代码，M2 无 Postgres，可接受但无测试）；`app/db.py:33-34` 的 `get_session` 在测试里永远被 dependency override，真实装配未执行；`app/dependencies.py:12-14` 的 `yield from get_session()` 同理；`app/dependencies.py:21-28` 是 `get_story_planner` 的成功装配路径，只在配了 key 时才走；`app/api/stories.py:128-129` 是 `BlueprintStorageError→42201` 分支，而 planner 已经用同一个验证器验过同一份 blueprint，此分支实际不可达。建议：前四项补装配级测试（临时 SQLite 文件、配置一个假 key 后只构建不调用），最后一项要么删掉、要么改成独立的存储失败码并加日志，别把“存储失败”伪装成“生成失败”。

## Residual risks / missing verification

- 本轮没有独立重跑测试：`pytest` 命令被权限层拦截，`progress.md` 自述的 `137 passed` / `16 passed` 只按代码与测试内容核对，未取得本轮执行证据。
- `alembic downgrade` 按 `PLAN.md` 边界未实跑，只做了静态检查：drop 顺序为先索引后表、子表先于父表，看起来可逆，但没有运行证据。
- `PLAN.md` 第 5 问（状态变化表能否支撑回放）：`sequence/entity_key/before_state/after_state/source` 的结构够用，但缺“玩家动作/幂等键”字段，同一动作重放两次无法识别；`entity_key` 的全局唯一性（尤其 choice key）目前只靠 `BlueprintValidator` 保证，数据库只做 `(episode_id,key)` 唯一；如果将来有绕过验证器的写入方，`entity_key` 可能歧义。留给第 3 批决定。
- `PLAN.md` 第 6 问（SQLite 坑）：外键逐连接开启已做；WAL、busy_timeout 未做（P3）；相对路径默认值已在 `app/models/__init__.py` 文档说明；迁移可逆性只有静态证据。
- 世界事实与叙述的分离总体成立（`app/models/__init__.py:55-68`）：叙述列不可变、`current_value` 是唯一可变 metric 字段；但 `Choice.effects` / `Ending.conditions` 存 JSON，库层无法约束 metric_key 存在性，完全依赖导入时验证器，这是已声明的取舍，需在第 3 批写入方继续守住。

结论：不通过
