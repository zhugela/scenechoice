# 会话交接

> 最近一轮：Session 001（2026-11-12），harness 铺设 + 环境修复。

## 当前已验证

- 明确可用的部分：M0 工程底座、M1 故事规划实现（Schema + Validator 十条规则 + 重试 + API 契约 + 日志追踪）。
- 这轮实际跑过的验证：`.venv/Scripts/python.exe -m pytest -q` → `94 passed`；`init.sh` → 依赖同步 + 94 passed + 打印启动命令，退出码 0。
- 未在本轮复跑：真实 DeepSeek 20 题评测（证据沿用 2026-11-07 的 `evals/reports/story-planning-20261107-013109.json`，20/20）。

## 本轮改动

- 修复半装损坏的 `.venv`（pluggy / pytest / pydantic 缺文件），现已能正常跑测试。
- 铺入 harness 状态层：`AGENTS.md`（新增 Session Startup & Handoff 一节）、`progress.md`、`feature_list.json`、`init.sh`、`check.ps1`、`session-handoff.md`、`clean-state-checklist.md`、`evaluator-rubric.md`、`quality-document.md`。
- 修正 `AGENTS.md`：学习任务「重复角色引用」已由本人完成（`a6b08cf`），CI 文件名改为 `.github/workflows/ci.yml`。

## 仍损坏或未验证

- 已知缺陷：业务流程第 10 条「不依赖未定义的关键道具」仅靠 Prompt + 人工评分，无结构化校验。
- 未验证路径：修复 `.venv` 后未复跑真实 20 题评测；沙箱化安装依赖网络受限，`pip install` 在此环境不可靠。
- 下一轮注意：不要用 `pip` 手动补装去修 venv（此环境无网会静默失败），必要时用 `uv pip install --reinstall -r requirements.txt`。

## 下一步最佳动作

- 最高优先级未完成功能：`sc-m1-03` 负责人个人掌握验收。
- 为什么它是下一步：M1 阶段门只差这一条；实现与真实评测两条已 passing。
- 什么结果才算 passing：`docs/learning/scenechoice-m1-learning-review.md` 六项全部勾选，且能脱稿讲清数据流与五道口述题。
- 不要动：`tests/` 已有用例的预期结果、M1 阶段门门槛、任何 Pydantic/Validator 规则。

## 命令

- 启动：`.venv/Scripts/python.exe -m uvicorn app.main:app --reload`
- 验证：`.venv/Scripts/python.exe -m pytest -q`（或 `./init.sh` / `powershell -File check.ps1`）
- 定向调试：`.venv/Scripts/python.exe -m pytest tests/test_blueprint_validator.py -q`
