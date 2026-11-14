# 进度日志

<!--
每次开工先读这个文件，收工写完再走。任何 coding agent 都不会自动维护它，
只有 AGENTS.md 里明确要求了，agent 才会读/写。
-->

## 当前已验证状态

- 仓库根目录：`D:\zhugela-hub\scenechoice`
- 标准启动路径：`.venv/Scripts/python.exe -m uvicorn app.main:app --reload`
- 标准验证路径：`.venv/Scripts/python.exe -m pytest -q`（2026-11-12：94 passed）
- 一键体检：`./docs/harness/init.sh`（在 git-bash 里跑；会装依赖 + 跑全部测试 + 打印启动命令）或 `powershell -File docs/harness/check.ps1`
- 当前最高优先级未完成功能：`sc-m1-03` 负责人个人掌握验收（学习清单 6 项未勾）
- 当前 blocker：M1 阶段门卡在"个人掌握"这一条，实现与真实评测两条已过

## 会话记录

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
