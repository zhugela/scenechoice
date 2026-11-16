# PLAN — M2 第 5 批：修评审的 P1 + endings 排序 bug

`docs/harness/reviews/latest.md` 评出 1 个 P1 和 6 个 P2。**本批只修两条硬伤**，其余留到下一批。

## 要修的两条

### ① [P1] 存档/恢复只恢复了生成态，玩法进度全丢

**现状**（评审原文）：
- `story_store.py:80` 写入 `Metric.current_value`
- `story_store.py:95` 写入 `Episode.status`
- `story_store.py:156-167` 写入 `story_state_changes`
- 但 `load_blueprint`（`story_store.py:172-262`）只按 `StoryBlueprint` 还原 `initial_value`，**上面三处从不读**
- 详情响应（`schemas/stories.py:34-36`）只有 `public_id + blueprint`

**后果**：玩家推进剧情后按 `public_id` 恢复，回到初始状态。M2 吸收点③「存档/恢复体验」实际没交付。

**修法（二选一，你定并说明理由）**：
- A. 新增 `GET /api/stories/{public_id}/state`，返回每集状态 / 各 metric 当前值 / 最后 sequence / 最近状态变化。`blueprint` 仍是静态骨架，`state` 是动态进度，两者分开。
- B. 让 `GET /api/stories/{public_id}` 的响应里加 `state` 字段，一次拿全。

**推荐 A**（职责分离，且 M3 玩家界面只需要 state 轮询）。但你要真觉得 B 对就说理由。

**验收**：
- 造一个 story → 手改库里 `metric.current_value=7`、`episode.status='played'` → 调恢复接口 → **能读回 7 和 played**（贴证据）
- 补测试守这条（不能只测"初始值还在"）

### ② [P2] endings 回读按 priority 重排，合法输入顺序会丢

**现状**：
- `models/story.py:104-109` 关系用 `order_by="Ending.priority"`
- `blueprint_validator.py:142-144` 只要求 priority 唯一，**不要求数组按 priority 升序**
- 所以 `endings=[priority 2,1,3]` 存进去，读出来变 `[1,2,3]`，`model_dump()` 不相等

**修法**：照 `Character.position` 的做法，给 `endings` 加 `position` 列，保存时记录数组下标，读回按 position 排。
**需要新建一个 Alembic 迁移**（不改已发布的 `20261115_0001`）。

**验收**：
- 用 `endings` 顺序为 `[2,1,3]` 的 blueprint 做往返，断言顺序保持
- 新迁移能 `alembic upgrade head` 跑通，且对已有数据不炸（老数据 position 补 0 后按 priority 兜底排序也可以，说明你的策略）

## 不许做的事

- 不许顺手改其他 P2/P3（下批专门做，混在一起会看不清）
- 不许改 M1 的 `preview` 行为
- 不许 git add / commit / push
- 不许动已发布的 `20261115_0001` 迁移文件，只能新增

## 验收底线

1. `.venv/Scripts/python.exe -m pytest -q` 全绿（当前 137，新增后应 >137）
2. P1 的"改库后能读回"有实测证据
3. endings 乱序往返有测试且通过
4. `alembic upgrade head` 在**已有数据**的库上也能跑（别只测空库）
