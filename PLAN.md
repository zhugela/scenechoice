# PLAN

目标：修复巡检报告 P2-1 —— 规则 4（两个选择必须方向不同）能被「delta: 0 的假效果」绕过。

## 约束

1. 不许改 `tests/` 里已有用例的预期结果，只允许新增。
2. 只许收紧校验，不许放宽；不许为了让测试变绿删规则。
3. 每处改动必须配测试。
4. 收工前 `.venv/Scripts/python.exe -m pytest -q` 必须全绿（当前基线 **98 passed**）。
5. 不许 `git add` / `git commit` / `git push`。
6. 只动本 PLAN 点名的范围，别顺手重构。

## 背景事实（已核实，不要重新推测）

- 问题位置：`app/services/blueprint_validator.py:82-86`（比较两集选择的效果）与 `:93-94`（非零检查）
- 当前实现：
  ```python
  first_effects = sorted((effect.metric_id, effect.delta) for effect in first.effects)
  second_effects = sorted((effect.metric_id, effect.delta) for effect in second.effects)
  if first_effects == second_effects:
      issues.append(ValidationIssue(f"{path}.choices", "choices must lead in different directions"))
  ```
- 反例（报告原文）：
  - 选择 A：`effects=[{"metric_id":"reputation","delta":10}]`
  - 选择 B：`effects=[{"metric_id":"reputation","delta":10},{"metric_id":"mindset","delta":0}]`
  - 两个排序列表不相等 → 不报「方向不同」；B 含非零 delta → 规则 6 也不报
  - **实际状态变化完全相同**，模型只要补一个 `delta: 0` 就能绕过
- 设计依据：设计文档 `:121`「每集两个选择的意图和后果不能完全相同」
- 报告建议：比较前剔除 `delta == 0` 的效果，再判断非零效果集合是否相同；补对应测试

## 子任务队列

- [ ] 基线确认：`.venv/Scripts/python.exe -m pytest -q`，记录 passed 数量
- [ ] 复现缺陷：写一条测试 —— 上面那个反例（A 只有 reputation+10，B 多一个 mindset:0），断言当前**不报错**，先让它红着当证据
- [ ] 修：比较前剔除 `delta == 0` 的效果（注意：如果剔除后两边都为空，要按「两个选择都没效果」处理，想清楚这种情况该报什么错）
- [ ] 把复现测试改成断言**必须报错**（变绿）
- [ ] 补第二条测试：两个选择效果确实不同时（如 A: reputation+10，B: reputation-10）必须通过 —— 防过度收紧
- [ ] 补第三条测试：覆盖「剔除 delta:0 后相等」与「一侧全零」两个边角
- [ ] 修正文档表述：`docs/quality/2026-11-06-scenechoice-m1-acceptance-audit.md:52` 写着「intent 与 effect 同时比较」，但代码从未读取 `choice.intent`。改成「仅比较 effects」，并注明 intent 字段当前未被使用（**只改这一处表述，不要删字段、不要加 intent 校验**）
- [ ] 跑全量测试，把结果写进 `docs/harness/progress.md`（新开 Session 004 段落）
- [ ] 输出改动摘要：改了哪几处、边角怎么处理的、新增几条测试

## 不要做的事

- 不要动 `app/schemas/story_blueprint.py` 的 `intent` 字段本身
- 不要碰 `app/clients/deepseek.py` 的错误码映射（那是 P2-2，需要本人先决策）
- 不要碰规则 10（P2-3，需要本人先决策）
- 不要重构 validator 整体结构
