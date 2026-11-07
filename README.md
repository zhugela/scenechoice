# 幕择 SceneChoice

[![SceneChoice CI](https://github.com/zhugela/code2/actions/workflows/scenechoice-ci.yml/badge.svg)](https://github.com/zhugela/code2/actions/workflows/scenechoice-ci.yml)

> 一句话生成一部由你决定结局的互动短剧｜当前阶段：M1 故事规划 PoC 已实现，等待真实模型评测门

> 阶段判定：代码实现完成，但 M1 尚未放行。真实 16/20 评测和负责人个人验收完成前，不进入 M2。

用户输入一句故事灵感并选择 3 集或 5 集。玩家在每集结尾做出关键选择，规则引擎计算人物关系和核心状态变化，AI 负责把已经确定的事实叙述成短剧，并在 5～10 分钟内收束到明确结局。

## 已完成：M0 工程骨架

1. ✅ FastAPI 应用与 `/health` 健康检查；
2. ✅ `pydantic-settings` 配置管理与 `.env.example`；
3. ✅ 统一响应、统一异常和 request ID；
4. ✅ pytest 健康检查、配置、异常与 request ID 测试（当前 10 条）；
5. ✅ 验收：Uvicorn 可启动、测试全绿、DeepSeek Key 不入库。

## 已实现：M1 故事规划 PoC

使用 DeepSeek 和 Pydantic 实现“一句话 → 标题、角色、两个核心状态、3/5 集大纲和结局条件”：

1. ✅ 严格 JSON Schema 与跨字段业务校验；
2. ✅ 无效输出自动修复，最多三次模型调用；
3. ✅ `POST /api/story-plans/preview` 预览接口，不写数据库；
4. ✅ 20 个不同题材的固定评测集和 16/20 阶段门；
5. ✅ 评测报告保存蓝图、耗时、Token 与人工评分栏；
6. ⏳ 使用真实 DeepSeek Key 执行线上评测。

数据库、RAG、LangGraph、正文生成和前端仍不在 M1 范围内。

## 本地运行

```powershell
Copy-Item .env.example .env
# 在 .env 中填写 SCENECHOICE_DEEPSEEK_API_KEY（不要提交 .env）
python -m uvicorn app.main:app --reload
```

接口示例：

```http
POST /api/story-plans/preview
Content-Type: application/json

{"inspiration":"新人游戏主播误开全队麦后被恶意剪辑","episode_count":3}
```

运行测试和真实 20 题评测：

```powershell
python -m pytest -q
python evals/run_story_planning_eval.py --episodes 3
```

评测脚本未发现 Key 时会退出并提示“未执行”，不会生成虚假的成功报告。

项目依据：

- [立项书](docs/product/scenechoice-project-charter.md)
- [竞品分析](docs/product/scenechoice-competitor-analysis.md)
- [产品设计](docs/plans/2026-10-26-scenechoice-design.md)
- [M1 故事规划 PoC 设计](docs/plans/2026-11-05-scenechoice-m1-story-planning-design.md)
- [M1 实施计划](docs/plans/2026-11-06-scenechoice-m1-implementation.md)
- [M1 学习复盘与个人验收](docs/learning/scenechoice-m1-learning-review.md)
- [M1 阶段验收审计](docs/quality/2026-11-06-scenechoice-m1-acceptance-audit.md)
- [竞品能力吸收决策](docs/plans/2026-11-06-scenechoice-competitor-capability-adoption.md)
- [15K 岗位能力矩阵](docs/career/scenechoice-15k-competency-matrix.md)
