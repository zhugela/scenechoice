# SceneChoice AI 工具协作流程

## 分工

| 工具 | 主要职责 | 不负责 |
|---|---|---|
| Hermes | 学习教练、知识复习、进度记忆、每日小练习 | 自动代写保留给学习者的任务 |
| Claude Code | 独立只读代码审查 | 默认不修改、提交或推送代码 |
| Codex | 需求落地、编码、测试、修复和交付 | 不替代学习验收与独立审查 |

三者共享同一个仓库事实，但不要让三个工具同时修改同一工作区。

## Hermes：项目学习

项目工作区命名为 `SceneChoice`，主目录是 `python-ai-agent-growth/scenechoice`。Hermes 会自动读取该目录的 `AGENTS.md`。

建议从项目目录启动：

```powershell
hermes --tui --in D:\code2\python-ai-agent-growth\scenechoice
```

第一句可以说：

```text
根据 AGENTS.md 和真实代码带我复习 M1。一次只讲一个知识点，先问我再揭晓答案，并记录我的掌握情况。不要替我完成保留的亲手任务。
```

以后继续同一学习会话：

```powershell
hermes --tui --resume latest --in D:\code2\python-ai-agent-growth\scenechoice
```

## Claude Code：独立审查

Claude 会自动读取项目目录的 `CLAUDE.md`。在项目目录运行：

```powershell
claude -p "按 CLAUDE.md 对当前 SceneChoice M1 做只读代码审查。检查完整项目而非只看 Git diff，不要修改文件。"
```

审查结果必须先由人或 Codex 验证，不能因为 Claude 提出问题就直接修改。正确流程是：

```text
Claude 发现问题
→ Codex/人类复现并判断是否成立
→ 成立则补失败测试
→ 实现最小修复
→ 本地测试与 GitHub CI
→ 必要时让 Claude 复审
```

## 冲突处理

- 产品范围以立项书和阶段验收报告为准；
- 测试结果和可复现行为优先于任一模型的主观看法；
- Claude 与 Codex 意见不一致时，先写最小复现测试；
- Hermes 记录的“学会了”必须由学习者回答或亲手修改证明；
- 任何工具都不能读取、输出或提交 API Key。
