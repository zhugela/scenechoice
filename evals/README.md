# M1 故事规划评测

## 阶段门

运行固定 20 题后，至少 16 题通过 Pydantic 与业务规则校验，才算通过结构阶段门。

```powershell
python evals/run_story_planning_eval.py --episodes 3
```

报告生成在本地 `evals/reports/`，该目录不会提交到 Git。报告保留每题的蓝图、重试次数、耗时和 Token；失败项保存脱敏后的异常类型与结构校验问题，不保存 API Key、完整模型响应或其他敏感配置。

普通 `pytest` 是严格离线的：测试会隔离本机 `.env` 和 `SCENECHOICE_*` 环境变量，并禁止连接外部网络。只有本评测命令允许调用真实 DeepSeek。

## 人工评分

结构正确不代表故事好看。评审者需要为每题的四项指标分别填写 0～2 分：

| 字段 | 0 分 | 1 分 | 2 分 |
|---|---|---|---|
| `complete_arc` | 没有收束 | 勉强完整 | 开端、冲突、反转、结局清楚 |
| `theme_relevant_metrics` | 状态无关 | 一个状态相关 | 两个状态都紧扣主题 |
| `meaningful_choices` | 选择同质 | 部分有差异 | 每集选择都代表不同策略和后果 |
| `distinct_endings` | 结局同质 | 有一定差异 | 低、高、混合结局明显不同 |

将 `manual_review.status` 改为 `completed`，填写各项分数、总分和简短说明。不要只评成功案例；失败项也要保留在报告中。

结构阶段门负责证明“软件能执行”，人工评分负责判断“用户是否愿意玩”。两者不能互相替代。
