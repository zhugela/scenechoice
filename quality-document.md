# 质量文档（SceneChoice）

每个产品领域和架构层的质量快照。用来判断"这个代码库是在变强还是变弱"，
和 `evaluator-rubric.md`（评单轮 agent 输出）不是一回事。

**更新时机：** 每轮重要会话结束后，或开始新里程碑前。
**评级标准：** A=验证全绿且干净可读 / B=验证通过但有少量缺口 / C=部分可用有已知缺口 / D=不可用或结构有问题。

> 2026-11-12 首次填写，依据 `docs/quality/2026-11-06-scenechoice-m1-acceptance-audit.md` 与当日 `pytest -q`（94 passed）。

---

## 产品领域

| 领域 | 评级 | 验证状态 | Agent 可读性 | 测试稳定性 | 关键缺口 | 上次更新 |
|------|------|---------|-------------|-----------|---------|---------|
| 蓝图结构约束（Pydantic） | A | Schema 单测全绿 | 高，字段自带 description | 稳定 | 无 | 2026-11-12 |
| 跨字段业务规则（Validator） | B | 规则单测全绿 | 中，10 条规则集中在 `validate()` | 稳定 | 第 10 条"关键道具"只做到部分实现，没有结构化 `items` 注册表，靠 Prompt + 人工评分 | 2026-11-12 |
| DeepSeek 调用与错误分类 | A | MockTransport 单测 + 401/429/损坏响应测试 | 高 | 稳定 | 真实网络抖动路径未长期观测 | 2026-11-12 |
| 自动修复与有限重试 | A | 无效 JSON / 连续失败单测 | 高 | 稳定 | 无 | 2026-11-12 |
| API 契约 | A | 强类型 response model + OpenAPI 合约测试 | 高 | 稳定 | 只覆盖 `story_plans` 一个入口 | 2026-11-12 |
| 请求追踪与日志 | A | request ID 跨中间件与 Planner 日志测试 | 高 | 稳定 | 无 | 2026-11-12 |
| 20 题真实评测 | B | 2026-11-07 20/20 通过 | 中，报告在 `evals/reports/` | 未重跑（花真实 token） | 证据是 11-07 的，环境修复后未复跑 | 2026-11-12 |

## 架构层

| 层级 | 评级 | 边界执行 | Agent 可读性 | 关键缺口 | 上次更新 |
|------|------|---------|-------------|---------|---------|
| `app/api/` | A | 只收参数调 service，不直接发 HTTP | 高 | 只有单个业务入口 | 2026-11-12 |
| `app/services/` | A | 业务规则全在这一层 | 高 | Validator 单函数较长，规则增加后需拆分 | 2026-11-12 |
| `app/clients/` | A | HTTP 只出现在这里 | 高 | 无 | 2026-11-12 |
| `app/schemas/` | A | 只定义形状，不含业务道理 | 高 | 无 | 2026-11-12 |
| `evals/` | B | 固定 20 样例 + 报告契约 | 中 | 报告产物需确认被 `.gitignore` 挡住（含完整正文与 token 明细） | 2026-11-12 |
| `tests/` | A | conftest 隔离 + 断网（MockTransport） | 高 | 无 | 2026-11-12 |

## 非代码域（同样算质量）

| 项 | 评级 | 说明 | 上次更新 |
|---|---|---|---|
| 负责人个人掌握 | D | `docs/learning/scenechoice-m1-learning-review.md` 6 个复选项 0 已勾选；M1 阶段门唯一未满足条件 | 2026-11-12 |
| 运行环境健康 | A | 修复前 .venv 半装损坏（pluggy/pytest/pydantic 均缺文件），`uv pip install --reinstall -r requirements.txt` 后 94 passed | 2026-11-12 |
| 仓库卫生 | A | 根目录中断安装垃圾（`pip-build-tracker-*` / `pip-install-*` / `pip-ephem-wheel-cache-*` / `pytest-of-Administrator` / `.venv.new/`）已于 2026-11-12 清理，当前干净 | 2026-11-12 |

## 变更历史

### 2026-11-12

- 变更内容：首次建立本文件；修复损坏的 `.venv`；铺入 harness 状态层（feature_list.json / progress.md / init.sh / 交接与评审模板）
- 提升：运行环境从"跑不起测试"恢复到 94 passed
- 下降：无
- 新发现的缺口：上述"关键道具"规则只做了一半；20 题评测未在修复后复跑
- 已关闭的缺口：根目录中断安装垃圾已清理
