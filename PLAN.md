# PLAN

目标：修复 M1 巡检报告里的 P1 缺陷——规则 9 目前只校验 `category` 标签，三个「标签不同、触发条件完全相同」的同质结局能蒙混过关。

## 约束

1. **不许改 `tests/` 里已有用例的预期结果**；只允许新增用例。
2. **只许收紧校验，不许放宽**；不许为了让测试变绿而删规则。
3. 每处改动**必须配一条测试**，没有测试的改动不算完成。
4. 收工前必须 `.venv/Scripts/python.exe -m pytest -q` **全绿**（基线 94 passed）。
5. 不动 M1 阶段门门槛，不动 `feature_list.json` 里已 passing 的条目判定。
6. 改完把结论追加到 `docs/harness/progress.md` 的会话记录里。

## 背景事实（已核实，不要重新推测）

- 问题位置：`app/services/blueprint_validator.py:96-98`
  ```python
  categories = {ending.category for ending in blueprint.endings}
  if categories != {"low", "high", "mixed"}:
      issues.append(ValidationIssue("endings.category", "must include low, high and mixed"))
  ```
- 设计依据：`docs/plans/2026-11-05-scenechoice-m1-story-planning-design.md:126` 要求「必须存在高值、低值和中间/混合路径，避免三个同质结局」。
- 反例：三个结局分别标 `low` / `high` / `mixed`，但 condition 全是
  `[{"metric_id": "reputation", "operator": "gte", "value": 70}]`，priority 分别 1/2/3
  → 当前 `validate()` 返回空列表，校验通过。
- 可用工具：`blueprint_validator.py:30-38` 已有条件可达性判定，`:99-101` 已有 priority 唯一性检查，`:102-107` 有状态区间逻辑——先读这三段再动手。

## 子任务队列

- [x] 基线确认：跑 `.venv/Scripts/python.exe -m pytest -q`，记录当前 passed 数量
- [x] 复现缺陷：写一条测试，构造「三同质结局」（category 不同但 condition 完全相同），断言当前**不报错**——先让它红着，作为缺陷证据
- [x] 修 P1-A：让不同 `category` 的 condition 签名不允许完全相同（怎么定义"签名"自己定，但要在代码注释里写清理由）
- [x] 修 P1-B：`low` / `high` 结局的可用区间要跟语义对得上——如果产品阈值确实没定义，就用最保守做法：要求 low 的结局不能在"只有高值可达"的区间内，并在注释标注「阈值待产品确认」
- [x] 把复现测试改成断言**必须报错**（变绿）
- [x] 补第二条测试：category 与条件都不同时，校验应当通过（防过度收紧）
- [x] 跑全量测试，全绿后把结果写进 `docs/harness/progress.md`
- [x] 输出一份改动说明：改了哪几行、为什么这么定"签名"、新增几条测试

## 不要做的事

- 不要碰 `app/schemas/story_blueprint.py` 的 `intent` 字段（那是下一个任务，本轮不做）
- 不要重构 validator 的整体结构，只加校验
- 不要提交 git（改完我来 review 后再决定提交）
