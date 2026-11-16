# PLAN — M2 第 2 批：Repository + 存档/恢复 API

## 本批范围

把已经校验通过的 blueprint **存进库**、按 id **恢复出来**。

**做**：Repository 层 + 领域转换 + 3 个 API 端点 + 往返测试
**不做**：状态变化记录逻辑（第 3 批）、玩家交互/剧情推进（M3）、并发控制

## 现状（第 1 批已完成，先读再动手）

已提交 `77df366`。已有：
- `app/models/`：Story / Character / Episode / Choice / Metric / Ending / StateChange（SQLAlchemy 2.0，`Mapped[...]` 风格）
- `alembic/versions/20261115_0001_initial_domain.py`，已实测建库成功（7 张业务表）
- `app/config.py` 有 `SCENECHOICE_DATABASE_URL`（默认 `sqlite:///./scenechoice.db`）
- `app/schemas/story_blueprint.py` 的 `StoryBlueprint` = **生成态**（LLM 产出 + 校验通过）
- M1 的 `POST /api/story-plans/preview` 是**纯预览不落库**，本批不许改它的行为

## 关键设计点

1. **生成态 → 持久化态的转换要收敛在一处**
   写 `app/services/story_store.py`（或 `app/repositories/`），负责
   `StoryBlueprint → ORM 模型树` 与 `ORM 模型树 → StoryBlueprint`（往返）。
   **不许在 API 层散落转换代码**，也不许把 Pydantic 对象直接塞进 ORM。

2. **事务边界**
   保存一个 story = 1 个事务，包含 story 本体 + 全部 characters/episodes/choices/metrics/endings。
   中途任何一步失败 → **整体回滚**，库里不许留半截故事。用 `Session.begin()` 或显式 commit/rollback。

3. **会话管理**
   SQLAlchemy 2.0 风格：`sessionmaker` / `Session`，通过 FastAPI 依赖注入（`app/dependencies.py` 加 provider），
   不要每次自己 `create_engine`。

4. **幂等与重复保存**
   同一个 blueprint 存两次怎么处理？给出选择并说明理由（新建一条新 story / 按 public_id 覆盖 / 报冲突）。

5. **不许破坏 M1**
   现有 **121 条测试**必须继续全绿；`preview` 接口行为一个字都不许改。

## 子任务队列

- [ ] 基线：`.venv/Scripts/python.exe -m pytest -q` 确认 **121 passed**
- [ ] 读 `app/models/*.py` 全部字段，以及 `app/schemas/story_blueprint.py` 的字段语义
- [ ] 写 `app/db.py`（engine + sessionmaker + get_session 依赖），从 `app/config.py` 读 URL
- [ ] 写 `app/services/story_store.py`：`save_blueprint(session, blueprint) -> Story` 与 `load_blueprint(session, public_id) -> StoryBlueprint | None`
- [ ] 写 `app/api/stories.py` 三个端点（挂到 main）：
  - `POST /api/stories`：入参 `{inspiration, episode_count}` → 生成 + 校验 + 落库，返回 `{public_id, ...}`
  - `GET /api/stories/{public_id}`：恢复出完整 blueprint
  - `GET /api/stories`：列表（分页，只返回摘要字段，不返回全部子实体）
- [ ] 测试（新建 `tests/test_stories_api.py`）：
  - 保存 → 恢复 → **逐字段比对**（往返一致）
  - 事务回滚：模拟中途失败（如塞一个非法子实体）→ 库里查不到半截 story
  - 重复保存的行为（按你上面选定的策略断言）
  - 404：查不存在的 public_id
- [ ] 跑全量测试，把真实结果写进 `docs/harness/progress.md`（新开 Session 007）
- [ ] 输出：3 个端点的请求/响应示例、事务回滚怎么验证的、重复保存策略与理由、新增几条测试、遗留问题

## 边界

- 不许改 `app/api/story_plans.py`、`app/schemas/story_blueprint.py`、`app/services/blueprint_validator.py`
- 不许写状态变化记录逻辑（但保存时**可以**写一条 `story_state_changes` 的 created 记录，这是最小必要）
- 不许 git add / commit / push
- 不许引 Postgres / 异步驱动（M2 用 SQLite 同步）
- 测试用**内存 SQLite**（`sqlite:///:memory:`）或临时文件，不许污染 `scenechoice.db`

## 验收（自己验证并把结果写进输出）

1. `pytest -q` 真实数字（基线 121 + 新增）
2. `POST /api/stories` 真的落库（保存后查表能看到 story + 子实体行数）
3. `GET /api/stories/{id}` 恢复出的 blueprint 与原始**逐字段相等**（写出你比对了哪些字段）
4. 事务回滚实测（贴出"失败后库里 0 行"的证据）
5. 121 条 M1 测试仍然全绿
