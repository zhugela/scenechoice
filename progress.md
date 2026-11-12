# 进度日志

<!--
每次开工先读这个文件，收工写完再走。任何 coding agent 都不会自动维护它，
只有 AGENTS.md 里明确要求了，agent 才会读/写。
-->

## 当前已验证状态

- 仓库根目录：`D:\zhugela-hub\scenechoice`
- 标准启动路径：`.venv/Scripts/python.exe -m uvicorn app.main:app --reload`
- 标准验证路径：`.venv/Scripts/python.exe -m pytest -q`（2026-11-12：94 passed）
- 一键体检：`./init.sh`（在 git-bash 里跑；会装依赖 + 跑全部测试 + 打印启动命令）
- 当前最高优先级未完成功能：`sc-m1-03` 负责人个人掌握验收（学习清单 6 项未勾）
- 当前 blocker：M1 阶段门卡在"个人掌握"这一条，实现与真实评测两条已过

## 会话记录

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
