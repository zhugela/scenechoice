# SceneChoice M1 Claude Code 审查报告（重建版）

> 说明：本报告根据 2026-11-06 的 Git 提交 `e0126f3c`、代码差异和测试结果重建。原始 Claude Code 会话报告未保存在仓库中，因此下列内容不是原始对话逐字稿，也不虚构 Claude 的原话。

## 审查结论

- 审查时结论：需要修改（Changes Required）
- 当前结论：已修复并通过测试
- 修复提交：`e0126f3c65053f81e1b3fbdf7ebbccce8160061e`
- 提交标题：`fix(scenechoice): turn malformed provider payloads into retryable errors`
- 协作记录：提交包含 `Co-Authored-By: Claude Haiku 5.5`

## 发现与处理结果

### 1. 高优先级：上游模型返回异常结构时可能泄漏为 HTTP 500

**问题**

DeepSeek 客户端直接按固定结构读取 `choices[0].message.content`。当服务返回非对象 JSON、空 choices、缺少 message，或 content 为 null/非字符串时，可能抛出 `AttributeError`、`TypeError`、`KeyError` 等非预期异常，最终表现为通用 HTTP 500，也无法进入已有的可重试错误链路。

**修复**

- 在客户端边界验证响应必须是对象。
- 验证 `choices`、首个 choice、`message` 和 `content` 的结构。
- 要求 `content` 必须是字符串。
- 对 `usage` 做类型保护，异常时使用空对象。

**证据**

- `scenechoice/app/clients/deepseek.py`
- `scenechoice/tests/test_deepseek_client.py`

### 2. 中优先级：规划失败原因没有进入评测报告，难以排查

**问题**

故事蓝图在多次修复后仍未通过校验时，`StoryPlanningError` 只保存尝试次数。评测报告只能看到异常类型，看不到具体违反了哪些规则，失败样例难以定位和复盘。

**修复**

- `StoryPlanningError` 增加 `issues` 字段。
- 重试和最终失败日志记录校验问题摘要。
- 评测结果增加 `failure_issues`，保存结构化失败原因。

**证据**

- `scenechoice/app/services/story_planner.py`
- `scenechoice/evals/run_story_planning_eval.py`
- `scenechoice/tests/test_story_planner.py`
- `scenechoice/tests/test_evaluation_cases.py`

### 3. 中优先级：蓝图规则和 Schema 边界测试覆盖不足

**问题**

已有测试不足以逐条证明蓝图校验规则和数据模型边界。规则变化后容易出现遗漏，且无法快速判断是哪条业务约束失效。

**修复**

- 增加逐规则的 validator 测试矩阵。
- 增加 Story Blueprint Schema 边界测试。
- 补充异常模型响应、规划失败信息持久化等回归测试。

**证据**

- `scenechoice/tests/test_blueprint_validator.py`
- `scenechoice/tests/test_story_blueprint.py`
- 本次提交共修改 8 个文件，新增 238 行、删除 7 行。

## 验证结果

2026-11-07 在当前远端同步版本重新执行测试：

```text
74 passed, 1 warning
```

唯一警告来自 Starlette `TestClient` 的弃用提示，不影响本次功能正确性。

## 后续流程改进

以后 Claude Code 完成审查时，除了修复提交，还应固定保存：

1. 审查范围与基准 commit。
2. 按严重程度排列的问题清单。
3. 每个问题的文件位置、影响和修复状态。
4. 测试命令与结果。
5. 未解决风险和最终结论。

报告统一存放在 `docs/reviews/`，避免再次出现“代码已修复并推送，但找不到审查报告”的情况。
