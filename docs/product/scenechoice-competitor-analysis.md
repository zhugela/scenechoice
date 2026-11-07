# SceneChoice 竞品分析 V1.0

> 调研日期：2026-11-05｜用途：立项决策，不作为市场规模报告

## 1. 调研问题

SceneChoice 是否应当继续做，以及它怎样避免成为又一个“输入主题、AI 续写故事”的同质化项目？

## 2. 竞品版图

| 类型 | 代表产品 | 核心能力 | 对 SceneChoice 的启示 |
|---|---|---|---|
| AI 互动故事 | AI Dungeon、NovelAI | 自由输入、无限续写、长期记忆和世界设定 | 不与成熟产品竞争长篇和无限自由度 |
| 开源 AI 互动叙事 | InteractiveNovel、Aventuras、openovel、AI Story Gen | 分支生成、多模型、本地部署、状态或记忆管理 | “调用 LLM 续写”不是差异化，工程透明度才有开源价值 |
| 传统互动阅读 | 橙光、Squiffy | 人工分支、创作工具、作品分发和内容生态 | 借鉴可完成的作品结构与分享机制，不在 MVP 做平台生态 |

## 3. 关键发现

### 3.1 同质化风险

InteractiveNovel 已覆盖“设置主题和风格、逐章选择、AI 生成封面、作品广场”。如果 SceneChoice 仍定位为通用 AI 分支小说，它只能成为功能更少的替代品。

### 3.2 市场空位假设

现有 AI 故事产品普遍强调自由和无限，SceneChoice 选择相反方向：

> 一句话生成一部能在 5～10 分钟内完成、拥有明确结局的 3 集或 5 集互动短剧。

这个方向仍是假设，必须通过 PoC 和至少 10 位真实体验用户验证，不能把竞品缺口直接当成用户需求。

### 3.3 技术差异化

采用“规则决定发生什么，AI 决定怎样讲”的架构：

1. 后端状态引擎计算选择后果；
2. AI 根据确定的事实生成短剧文本；
3. Pydantic 校验结构；
4. 一致性检查阻止人物、关系和状态漂移；
5. 调试视图公开状态、Prompt、耗时和 Token，形成开发者可学习的开源价值。

## 4. 竞品能力取舍

### MVP 必须具备

- 一句话创建故事；
- 3 集或 5 集且保证完结；
- 每集两个选择；
- 两个随故事生成的核心状态；
- 状态变化可见；
- 保存并继续故事；
- 至少三类结局；
- 移动端竖屏阅读体验。

### 可借鉴但后置

- AI Dungeon 的长期记忆；
- NovelAI 的 Lorebook；
- InteractiveNovel 的作品广场；
- 橙光的作者和素材生态；
- openovel 的多智能体运行时。

## 5. 立项结论

有条件立项。先用 20 个差异化题材测试故事规划 PoC；至少 16 个输出满足结构完整、状态合理、3/5 集可完结，才进入完整互动执行和前端开发。

## 6. 参考项目

- <https://github.com/doublele68/InteractiveNovel>
- <https://github.com/AventurasTeam/Aventuras>
- <https://github.com/Feed-Scription/openovel>
- <https://github.com/TreyEvreux/AI_Story_Gen>
- <https://github.com/textadventures/squiffy>
- <https://help.aidungeon.com/faq/the-memory-system>
- <https://docs.novelai.net/en/text/textadventure/>
- <https://www.66rpg.com/>
