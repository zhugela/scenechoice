# SceneChoice M1 测试代码独立审查报告

> 审查日期：2026-11-07
>
> 审查对象：`tests/`、`app/`、`evals/`、M1 设计基线、M1 验收审计
>
> 审查方式：只读代码核对 + 内存内探针复现（全流程未修改被审代码）
>
> 基线证据：`python -m pytest -q` → `74 passed, 1 warning in 1.28s`

## Review verdict: CHANGES REQUIRED

结论先行：

1. 74 条测试对 Schema 约束、Validator 规则、DeepSeek 错误分类、重试退避、request-id 追踪的覆盖是真实的，不是假通过。
2. 但存在 2 个 P1：API 错误映射有缺陷且该分支无测试；测试套件不隔离环境，配置 Key 时会触发真实网络请求。
3. 测试全绿不能证明 M1 达到验收标准。这与验收审计自身结论一致（`docs/quality/2026-11-06-scenechoice-m1-acceptance-audit.md:5-6`：实现完成、阶段门未通过）。

---

## Findings

### [P1] 认证/权限类错误被统一映射为 502「暂时不可用」，且 502/42201 分支完全没有测试

- Location: `scenechoice/app/api/story_plans.py:34-39`（`except DeepSeekClientError → 502 / 50201`）；`scenechoice/tests/test_story_plans_api.py:18-48`（仅覆盖 200/422/503）
- Evidence:
  - 探针：让 client 抛 `DeepSeekClientError(retryable=False, status_code=401)`，接口返回 `502 {"code": 50201, "message": "story model is temporarily unavailable"}`。
  - `grep` 测试目录：除 OpenAPI 里 schema `$ref` 外，没有任何测试断言 502 或错误码 50201/42201（`scenechoice/tests/test_story_plans_api.py:61` 只校验文档里存在 502 的 `ApiResponse` 引用）。
  - 规划失败 `StoryPlanningError → 422 / 42201`（`scenechoice/app/api/story_plans.py:38-39`）同样无测试。
- Impact:
  - 401（Key 失效/权限不足）是永久错误，却对客户端返回「temporarily unavailable」，会诱导上层无限重试；监控也会把配置错误误报成模型抖动。这与验收审计第 5 节「API 区分请求错误、规划失败、模型不可用和未配置模型」的声明不符。
  - 错误契约最重要的两条分支（502/42201）在没有测试的情况下被标为"已证明"，属过度声明。
  - 顺带：`scenechoice/tests/test_story_plans_api.py:42-48` 只覆盖 Key 为 `None`，未覆盖空串/纯空格 Key（`scenechoice/app/dependencies.py:9-10` 有该分支）。
- Recommendation: 按 `status_code` 分流（401/403 使用独立语义错误码并标记不可重试）；补 3 条 API 测试：永久认证失败、三次规划失败→42201、空串 Key→50301。

### [P1] 测试套件不隔离环境：存在 `.env` 或导出 Key 时，安全测试会发起真实 DeepSeek 请求并失败

- Location: `scenechoice/tests/test_story_plans_api.py:42-48`；`scenechoice/tests/test_config.py:7-13`；根因 `scenechoice/app/config.py:19-24`（`env_file=".env"`）、`scenechoice/app/config.py:27-29`（`@lru_cache`）；仓库无 `conftest.py`
- Evidence（复现命令结果）：

  ```
  SCENECHOICE_DEEPSEEK_API_KEY=dummy SCENECHOICE_APP_ENV=prod \
    pytest tests/test_story_plans_api.py::test_preview_requires_configured_model \
           tests/test_config.py::test_settings_have_safe_defaults
  → 2 failed

  test_preview_requires_configured_model: 实际发起网络请求，日志
    "model_error ... status_code=401 ... duration_ms=1760"
  test_settings_have_safe_defaults: assert 'prod' == 'development'
  ```

- Impact:
  - 「74 passed」是环境相关结论，不是代码内置保证。运行 M1 评测必须配置 Key（`scenechoice/evals/README.md:7-9`），开发者只要在 `scenechoice/.env` 放 Key，该测试就会真实调用外部 API：测试既不稳定，又产生费用和凭据外泄面。
  - 该失败由测试代码缺少隔离引起（未清 `lru_cache`、未屏蔽 `env_file`），不是运行环境缺陷——修复点在 tests，不在运行时。
- Recommendation: 增加 `scenechoice/tests/conftest.py`（autouse fixture）：`get_settings.cache_clear()`、`monkeypatch.delenv`/`Settings(_env_file=None)`、显式覆盖 `get_story_planner`；对「未配置」用例显式构造无 Key 的依赖，不依赖"环境恰好干净"。

### [P2] DeepSeek 请求体的核心可靠性参数无任何断言

- Location: `scenechoice/app/clients/deepseek.py:56-68`；`scenechoice/tests/test_deepseek_client.py:19-34`
- Evidence: 现有测试只断言 `Authorization` 头与 URL path。`grep response_format|temperature|json_object tests` 结果为空。`response_format={"type":"json_object"}`（`scenechoice/app/clients/deepseek.py:65`）是保证结构化输出的关键，测试却只校验了返回解析。
- Impact: 若有人删除 `response_format`、改错 `model`、去掉 `temperature` 或 `timeout`，74 条测试仍全绿；这类回归会直接抬高无效 JSON 率与重试成本，而评测工具无法在离线测试中暴露。
- Recommendation: 在 MockTransport handler 内解析 `request.content`，断言 `model`、`response_format.type == "json_object"`、`temperature`，并断言 `httpx.AsyncClient(timeout=...)` 被使用。

### [P2] 可观测性与隐私声明无测试支撑（token/attempts/duration/model 日志、灵感与 Key 不上日志）

- Location: `scenechoice/app/services/story_planner.py:76-84 / 99-107 / 132-139`；`scenechoice/tests/test_story_plans_api.py:64-77`
- Evidence: 唯一相关测试只断言 `request_id=trace-story-123` 出现在日志里。没有任何断言：
  - 成功/失败日志包含 `model`、`attempts`、`prompt_tokens`、`completion_tokens`、`duration_ms`；
  - 日志不包含用户灵感原文或 API Key。
- Impact: 审计第 5 节把「日志记录模型、尝试次数、耗时、Token，不记录完整灵感和 Key」列为已证明，但实际是未验证的声明。未来若把完整 prompt/response 打进日志（隐私与成本问题），测试不会失败。
- Recommendation: 用 `caplog` 补两条：成功路径断言字段齐全且不含 inspiration 子串；失败路径断言脱敏。

### [P2] 规则 4 可被"只改意图文案"绕过；规则 8 只用单指标单条件，跨指标组合从未被测

- Location: `scenechoice/app/services/blueprint_validator.py:80-84`（选择差异判定）；`scenechoice/app/services/blueprint_validator.py:30-38,100-105`（可达性枚举）；fixture `scenechoice/tests/blueprint_factory.py:77-105`（三个结局全部只引用 `reputation`）；测试 `scenechoice/tests/test_blueprint_validator.py:90-92,134`
- Evidence:

  ```
  RULE4: intent 不同但 effects 完全相同（都是 reputation +12）
    → issues = []   # 未被识别为"同向选择"
  ```

  且所有 Validator/Planner/API 测试复用同一个 3 集 fixture，三个结局均基于单一指标，`_ending_reachable` 的双指标笛卡尔积分支从未真正被跨指标条件触发（`survive` 的两条条件也是同一个 `reputation`）。
- Impact:
  - 模型可以输出两个"后果完全一样、只换文案"的选项而通过校验——这违背规则 4 的产品意图（选择应产生不同后果）。
  - 规则 8/9 的跨指标组合（例如 `reputation≥70 AND mindset≤30`）无任何测试；多指标可达性写错不会被发现。
- Recommendation: 补充"effects 相同且非空 → 判为同向"的判定与用例（至少 effects 相同应报；或在文档明确只按字面口径并降低审计表述）；新增一个双指标结局 fixture 覆盖 `product(repeat=2)` 的组合可达/不可达。

### [P2] 评测阶段门（≥16/20）的边界、失败归因与 `run()` 落盘/退出码未测

- Location: `scenechoice/evals/run_story_planning_eval.py:61-72`（gate 计算）、`:78-93`（`run()` 写报告、返回 0/1/2）；`scenechoice/tests/test_evaluation_cases.py:32-54,66-74`
- Evidence: 现有用例只跑 `total=1` 的单例（`gate_passed` 恒为 False），失败用例只覆盖 `StoryPlanningError`。未覆盖：
  - 恰好 16/20 的边界（`passed >= 16` 为真）；
  - `DeepSeekClientError` 被 `except Exception` 归为 structural fail 的路径（`:49-60`）；
  - `run()` 的三种退出码（0 通过 / 1 未达标 / 2 未配置 Key）与报告文件名/落盘。
- Impact: M1 的放行条件正是「≥16/20」，而这个阈值从未在测试里被跨过；阈值比较写错不会被测试捕获。评测脚本的落盘失败也可能静默。
- Recommendation: 构造 20 例（16 成功/4 失败）断言 `gate_passed is True`，15/20 断言 False；补 `DeepSeekClientError` 用例；用 `tmp_path` 测 `run()` 退出码与文件生成。

### [P2] 成本控制无法验证：请求无 `max_tokens`，修复轮重放上一条输出，且无测试约束

- Location: `scenechoice/app/clients/deepseek.py:62-67`（无 `max_tokens`）；`scenechoice/app/prompts/story_planning.py:22-31`（`repair_messages` 重放最多 12000 字符的上次输出 + 30 条问题）；`scenechoice/tests/test_story_planner.py` 无 token 上限断言
- Evidence: 请求体只有 `model/messages/response_format/temperature`。最坏路径为 3 次尝试 ×（system + 用户灵感 + 完整 JSON Schema + 12000 字符上一条输出），单次补全无上限。
- Impact: 设计 §3/§9 要求"控制成本"并能回答成本问题，但当前既无硬上限也无测试；一次失控补全可能产生远超预期的费用，评测的 token 统计也失去约束力。
- Recommendation: 为请求加 `max_tokens`（可配置并纳入 Settings 校验），补一条断言请求体包含该上限的测试；在评测报告里汇总平均 token 并断言字段存在。

### [P3] 客户端可重试状态码只验证了 429/超时，408 与 5xx 分支未测

- Location: `scenechoice/app/clients/deepseek.py:87-97`（`retryable = status in {408,429} or >=500`）；`scenechoice/tests/test_deepseek_client.py:46-54`
- Evidence: 测试覆盖 401、429、坏负载、超时；`grep` 无 408 与 5xx 用例。
- Impact: 5xx 是最常见的真实故障，其"可重试"判定若回退，测试不会失败。
- Recommendation: 参数化补 408 与 500/503 两条断言 `retryable is True`。

### [P3] 缺少 `DeepSeekClient → StoryPlanner` 的端到端串联测试

- Location: `scenechoice/tests/test_deepseek_client.py`（只测 client）、`scenechoice/tests/test_story_planner.py`（FakeClient 直接返回 `LlmReply`）
- Evidence: 两半各自测，但没有任何测试用 `httpx.MockTransport` 把真实 client 的输出 `content` 喂给 `StoryPlanner`，证明载荷形状→JSON→Schema→Validator 的接缝正确。
- Impact: 若 client 输出的字段名/结构变化（例如 `content` 取自错误位置），单测各自都通过，集成却断。
- Recommendation: 加一条 `StoryPlanner(DeepSeekClient(transport=MockTransport(...)))` 成功路径测试。

### [P3] 成功响应断言偏弱

- Location: `scenechoice/tests/test_story_plans_api.py:18-30`
- Evidence: 只断言 `episode_count` 与 `meta.model`，未断言 `meta.attempts/tokens/duration`、未校验返回蓝图本身能通过 `BlueprintValidator`、未断言 `X-Request-ID`。
- Impact: 响应体部分字段回归（如 meta 字段丢失、attempts 恒为 0）不会被发现。
- Recommendation: 对 `meta` 全字段与 `code/message` 做完整断言，并对 `data.blueprint` 再跑一次 Validator。

---

## Residual risks / missing verification

- M1 阶段门本身未达成：无真实 DeepSeek 20 题报告、无 16/20 证据、无人工故事评分。测试全绿只证明"软件可执行"，不证明"阶段门通过"（与验收审计一致）。
- CI 证据缺失：审计称 "GitHub Actions：Python 3.12、Ubuntu 24.04 自动执行"，但仓库内未找到 scenechoice 的 `.github/workflows`（仅在 `research/competitors/` 下找到他人仓库）。此条"已证明"缺乏可复核证据。
- 规则 8 只证明理论状态空间可达：`test_reachability_covers_state_space_not_playable_paths`（`scenechoice/tests/test_blueprint_validator.py:150-155`）明确承认"状态空间内可达 ≠ 玩法可达"。因此测试通过无法排除"蓝图在实际选择路径上无法抵达某些结局"。
- 规则 10（关键道具依赖）无结构化校验，也无测试：仅靠 Prompt 与人工评分，属已知部分实现。
- 真实 DeepSeek 行为未验证：`usage` 字段名、`Retry-After` 语义、`response_format=json_object` 的实际合规性与假响应是否一致，均需真实调用确认。
- 单一 fixture 偏差：几乎所有测试共用 `valid_blueprint_data()`，未覆盖 5 集路径下的 Validator 编号检查、双指标结局、空/边界文本长度等形态，可能掩盖形态相关缺陷。
- 测试运行产生真实副作用：已确认在 Key 存在时 API 测试会外出请求；该风险在无 `conftest.py` 时持续存在。

---

## 最小修复顺序

1. 修 P1-1（错误分流 + 3 条 API 测试）与 P1-2（`conftest.py` 隔离）；
2. 补 P2 的 client 参数、日志隐私、评测门边界三条；
3. P3 汇总为一次补齐。

在真实 20 题报告与人工评分完成前，维持「M1 不放行」。
