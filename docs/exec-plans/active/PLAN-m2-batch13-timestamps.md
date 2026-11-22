# PLAN — M2 第 13 批：时间戳带时区（naive → aware UTC）

> 来源：`docs/harness/reviews/latest.md` P3「时间戳以无时区形式返回」。
> 基线：`e6160e2`，`207 passed`。
> 本批对外**只改一个东西**：响应里时间戳带上 UTC 偏移；不改任何字段名、状态码、业务码。

## 一、现状事实

| 事实 | 证据 |
|---|---|
| 写入是 aware UTC | `app/models/base.py:32-39` `utcnow()` 返回 `datetime.now(timezone.utc)`，docstring 已写明「SQLite 读回 naive，读者按 UTC 解释」 |
| 响应直接吐 naive | `app/api/stories.py` 的 `_summary()` 把 `story.created_at` 原样塞进 `StorySummary`；状态端点的 `occurred_at` 同理 |
| 无任何测试断言过时间戳的时区 | `grep -rn "created_at\|occurred_at" tests/*.py` 只命中 `tests/test_migrations.py` 里的 isoformat 字符串 |

客户端拿到 `2026-11-20T02:39:52` 这种没有 `Z`/`+00:00` 的串，会按**本地时区**解析，非 UTC 机器上就偏 8 小时。

## 二、本批做什么

### U1 统一的「读回即 UTC」转换

- `app/models/base.py` 增加 `as_utc(value: datetime | None) -> datetime | None`：
  naive → 视作 UTC 补上 `tzinfo`；已 aware → 转成 UTC；`None` → `None`。
  docstring 写清它和 `utcnow()` 是同一件事的两端：「写的时候用 UTC，读的时候补回 UTC」。
- `app/api/stories.py`（以及任何吐时间戳的地方）改为经 `as_utc()` 输出：
  `StorySummary.created_at/updated_at`、`StoryStateChangeData.occurred_at`。

### U2 测试（3 条，只追加）

1. `POST /api/stories` → `GET /api/stories` → 列表里 `created_at` / `updated_at` 都是带偏移的 ISO 串（断言以 `+00:00` 结尾，或解析后 `tzinfo is not None`）。
2. 同一个故事 `GET /api/stories/{id}/state` → `recent_state_changes[0].occurred_at` 同样带时区。
3. 单元测试 `as_utc()`：naive 补 UTC、aware 转 UTC、`None` 原样返回。

### U3 文档

`docs/RELIABILITY.md` 或 `docs/ARCHITECTURE.md` 里补一句「API 时间戳一律 UTC，带偏移输出」——放哪你判断，只要有一处写下来。

## 三、禁改清单

- 任何字段名、状态码、业务码、message
- `app/schemas/story_blueprint.py`、`app/services/*`、`app/models/` 下除 `base.py` 以外的文件、`alembic/*`、`requirements.txt`
- 任何已有测试的预期结果

## 四、验收标准

1. `pytest -q` ≥ 210，已有用例零改动。
2. 变异测试：把 `as_utc()` 改成直接 `return value`（不补 tz）→ 用例 1、2 变红。
3. 手工证据：真实响应里时间戳形如 `2026-11-20T09:12:33.123456+00:00`。
