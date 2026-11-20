# PLAN — M2 第 11 批：外部审查（PR AI 审查）回灌

> 来源：PR #6 上 `github-actions[bot]` 的 AI 审查（DeepSeek）。它给了 2 条阻塞，Hermes 过滤后
> 2 条都算「建议看代价」并采纳，理由写在各条里。第 2 条的一半（双端一致性测试）已在批次 10 补上。
> 基线：`43801d6`，`201 passed`。

## 一、两条审查结论与处置

### U1 事务边界：路由里那句 `session.commit()` 是多余的

- 审查原话：`app/api/play.py` 里 `session.commit()` 写在路由函数里，违反「api 只收参数调 service」，
  且与 `create_story` 的口径不一致。
- Hermes 复核：`advance_story` 内部 `with session.begin():` 在成功退出时**已经提交**，
  路由那句是空事务提交，功能上多余；但「谁负责提交」这件事**没有任何测试钉住**。
- 处置：
  1. 删掉 `app/api/play.py` 里多余的 `session.commit()`，并把注释改成说清「引擎自己管事务边界」。
  2. 新增 1 条测试：推进成功后，用**新开 session**读库，必须读到推进后的指标值与
     `story_state_changes` 新行 —— 这条测试才是「引擎真的提交了」的证据，而不是靠巧合。
  3. 异常路径也补一条：推进失败（跨集选错）后，用**新开 session**读库，必须零新增行。

### U2 版本判断的单一来源

- 审查原话：详情接口的版本闸与推进引擎的版本闸看不到共用同一个比较，可能各写一套。
- Hermes 复核：两边确实各写了一次 `story.blueprint_version != BLUEPRINT_VERSION`，
  异常类型按层分开（详情是 `ValueError` 系、推进必须挂在 `PlayError` 下），这个分层是对的；
  但**比较逻辑**该只有一份。
- 处置：在 `app/blueprint_contract.py` 增加 `version_is_supported(stored: int) -> bool`，
  `story_store.load_blueprint` 与 `play_engine.advance_story` 都改用它；两个异常类型保持不动。

## 二、禁改清单

- 任何对外行为（状态码、业务码、message、响应字段）
- `app/schemas/*`、`blueprint_validator.py`、`conditions.py`、`app/models/*`、`alembic/*`、`requirements.txt`
- 任何已有测试的预期结果
- 各 feature 的 status

## 三、验收标准

1. `pytest -q` ≥ 203（U1 两条新增），已有用例零改动。
2. 变异测试：把 `version_is_supported` 改成恒 `True` → 双端一致性用例必须红。
3. `grep -n "blueprint_version != " app/` → 零命中（比较只在 `blueprint_contract` 里）。
4. `grep -n "session.commit()" app/api/play.py` → 零命中。
