# 自动化地图：谁在审、谁在守、谁该关

> 这份文件解决一个具体困惑：仓库里同时有几个「机器人」在评论，很容易记混谁装的、谁在干什么。
> 最后核对：2026-11-22。

## 三个审查，各管一段

| 名称 | 评论者 | 谁做的 | 触发点 | 它能看见什么 | 花钱吗 |
|---|---|---|---|---|---|
| **CI** | —（只给状态） | 项目自带（M0 就有） | 每次 push / PR | 跑 `pytest -q` | 免费 |
| **AI Review** | `github-actions[bot]` | **Hermes 写的**（提交 `1060518` 起，2026-11-18） | PR 打开/更新；CI 失败后诊断 | diff + 改动文件全文 | 每次 ≈ 3 万 token（¥0.1 级） |
| **Codex** | `chatgpt-codex-connector[bot]` | **GitHub App，仓库原有**，不是任何人装的 | 每个 PR | 只有 diff | 免费（走你的 ChatGPT 订阅） |
| **本机巡检** | 聊天里回你 | **Hermes 的 cron 任务** `f0b0cd805e33` | master 测试变红 | 能真跑测试、能看整仓 | 绿了 0 成本；红了 ≈ ¥1-2 |

## 记忆最容易错的地方

**「AI Review」不是 DeepSeek SuperAgent 装的。**

- `AI Review` = `.github/workflows/ai-review.yml` + `scripts/ai_review.py`，Hermes 于 2026-11-18 手写，
  经 PR #1 / #2 合并进 master，作者是 `朱远`（Agent 用你的 git 身份提交，所以看起来像你写的）。
- `DeepSeek SuperAgent` = `D:\zhugela-hub\dsh-superagent` 那套常驻 agent，同一晚装的，
  面板在 `http://127.0.0.1:3082`。它**不产生** `github-actions[bot]` 的评论——它发评论会用
  `zhugela` 本人的身份。而且它现在 **0 张工单**：源码里
  `if (sameName(item.user.login, login)) continue` 会跳过自己账号的动作，所以你不建小号它永远不会动。

一句话：**评论是 `github-actions[bot]` 发的 = AI Review（我写的）；是 `zhugela` 发的 = superagent（还没跑起来）；是 `chatgpt-codex-connector` 发的 = Codex（仓库原有）。**

## Codex：已关（2026-11-22 确认）

三个里唯一纯重复的是 Codex：每个 PR 固定一条 1211 字符的 summary，几乎不指出具体问题
（对比 AI Review 单条 3000～6000 字符、带 `文件:函数` 定位）。

关掉它两条路，任选一条：

1. **GitHub App 设置**（一次到位）
   <https://github.com/settings/installations> → `ChatGPT Codex Connector` → **Configure** →
   Repository access 里取消勾选 `scenechoice`（或直接 Uninstall）。
2. **Codex 自己的开关**
   <https://chatgpt.com/codex/cloud/settings/general> → 关掉这个仓库的自动 code review。

**状态（2026-11-22 实测）**：Codex 已关。探针 PR #9 上只有 `github-actions[bot]` 评论，
`chatgpt-codex-connector` 零评论。注意：关掉 App 只影响「以后还审不审」，
**已发出的评论是历史，不会消失**（PR #8 那条就是关之前 9 秒生成的）。

关完剩下两个，职责不重叠：

```
PR 阶段  →  AI Review 审 diff（合并前，能挡住）
master   →  本机巡检跑测试（合并后，红了才叫，绿了完全不打扰）
```

## 本机巡检现在是「只红才叫」模式

监控脚本：`C:\Users\Administrator\AppData\Local\hermes\scripts\scenechoice-master-watch.py`

- 它每 10 分钟把 `D:\zhugela-hub\scenechoice-watch`（只读副本）对齐到 `origin/master`，跑一次 `pytest`
- 输出**刻意不含提交号和时间**：`master-verdict=green passed=207`
- 输出不变 → Hermes 完全跳过 agent，**不花 token**
- 只有测试从绿变红（或红变绿）才唤醒 agent，它才会去定位、修复、推送

改这个行为只需要改那个脚本的输出内容；文案改动后第一次会唤醒一次，之后就稳定了。

## 三个副本，别搞混

| 目录 | 用途 | 谁在动 |
|---|---|---|
| `D:\zhugela-hub\scenechoice` | 你的主工作区 | 你 / 其他会话（现在是 `agentloop` 分支） |
| `D:\zhugela-hub\scenechoice-autopilot` | Hermes 做功能、开 PR 用的副本 | Hermes |
| `D:\zhugela-hub\scenechoice-watch` | 巡检专用只读副本，随时 `reset --hard` | 只有监控脚本 |
