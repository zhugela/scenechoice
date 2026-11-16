# PLAN — M2 第 1 批：领域模型 + ORM + 迁移骨架

## 本批范围（只做这些，别的都不许碰）

只做**数据层骨架**：领域模型设计 + SQLAlchemy 2.0 模型 + Alembic 首次迁移。

**不做**：Repository/DAO、API 接口、存档恢复逻辑、业务事务、测试（这些是第 2、3 批）。

## M2 总目标（背景，供设计时参考）

按 `docs/plans/2026-11-06-scenechoice-competitor-capability-adoption.md`：
- 本阶段实现 6 个领域实体：**Story、Character、Episode、Choice、Metric、Ending**
- 要有可恢复的故事存档
- 吸收点：① 世界事实与自然语言叙述分离 ② SQLite 迁移 + 事务边界 + 状态变化记录 ③ 存档/恢复体验

## 技术选型（已定，别换）

- **SQLite**（文档明确要求，M2 阶段不引 Postgres）
- **SQLAlchemy 2.0** 声明式（`Mapped[...]` / `mapped_column`，不用旧式 `Column`）
- **Alembic** 做迁移
- Python 3.12，用 `.venv/Scripts/python.exe`

## 关键设计约束（本批最需要想清楚的部分）

1. **生成态 ≠ 持久化态**
   现有 `app/schemas/story_blueprint.py` 的 `StoryBlueprint` 是"LLM 生成 + 校验通过"的产物，字段为校验服务。
   M2 的 SQL 模型为**长期存储 + 可恢复**服务。**不要直接把 Pydantic schema 当 ORM 模型**，要在注释里写清两者映射关系与差异理由。

2. **世界事实与叙述分离**（吸收点①）
   模型要能区分"已决定的事实"（metric 数值、ending 条件、choice 的 effect）和"叙述文本"（标题、描述、台词）。明确哪层可变、哪层生成后不可变。

3. **状态变化可追溯**（吸收点②）
   至少设计出"故事/剧集状态变化"的记录载体（history/audit 表，或不可变事实 + 投影）。**本批只建表结构，不写记录逻辑。**

4. **ID 策略**
   现有 blueprint 用字符串 id（如 character_ids）。持久化层要考虑：自增整数 PK + 业务字符串 id 双键？还是纯 UUID？**给出理由。**

5. **不破坏 M1**
   现有 121 条测试必须继续全绿。不许改 `app/schemas/story_blueprint.py`、`app/services/blueprint_validator.py`、`app/api/story_plans.py`。

## 子任务队列

- [ ] 基线：`.venv/Scripts/python.exe -m pytest -q` 确认 **121 passed**
- [ ] 读 `app/schemas/story_blueprint.py`，列出全部字段与语义
- [ ] 新建 `app/models/` 包，写 SQLAlchemy 2.0 模型：Story / Character / Episode / Choice / Metric / Ending
- [ ] 补一张状态变化记录表（命名自定），**只建结构不写逻辑**
- [ ] 建立实体关系（外键 + 级联策略，说明为什么这样设）
- [ ] `requirements.txt` 加 sqlalchemy / alembic（锁版本）
- [ ] `alembic init alembic`，配置 `alembic.ini` 与 `env.py` 指向项目配置里的 DB URL
- [ ] 生成第一个迁移（建全部表），**实际执行** `alembic upgrade head` 验证能建库
- [ ] 用 SQLite 实测：迁移后能查到 7 张表（6 实体 + 1 记录表）
- [ ] 跑 `.venv/Scripts/python.exe -m pytest -q` 确认仍是 **121 passed**
- [ ] 输出设计说明：字段与语义、实体关系（文字版）、ID 策略理由、生成态/持久化态映射差异、遗留问题

## 边界

- 不许写 Repository / Service / API 层代码
- 不许改 M1 任何业务文件
- 不许 git add / commit / push
- DB 路径走配置（`app/config.py` 加 `SCENECHOICE_DATABASE_URL`，默认 `sqlite:///./scenechoice.db`），不许硬编码
- `.gitignore` 补 `*.db`

## 验收（自己验证并把结果写进输出）

1. `alembic upgrade head` 真跑通（贴输出）
2. 查出 7 张表（贴输出）
3. `pytest -q` 仍 121 passed（贴输出）
4. 六个实体 + 1 张记录表的**字段清单**（表格）
5. ID 策略与生成态/持久化态映射的**理由**（不能只写"这样方便"）
