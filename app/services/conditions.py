"""Metric-condition evaluation shared by the blueprint validator and the play engine.

Validation asks "is this ending reachable at all?" and play asks "has it been
reached yet?" — the same question about the same data. Keeping one module for
it means the two can never disagree about what ``reputation gte 70`` means,
which is the same class of drift the provider error-mapping refactor removed on
the HTTP side.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

METRIC_MIN = 0
METRIC_MAX = 100


class Condition(Protocol):
    """Any object shaped like :class:`EndingCondition`."""

    metric_id: str
    operator: str
    value: int


def condition_matches(operator: str, actual: int, expected: int) -> bool:
    """Evaluate one comparison; an unknown operator is a programming error, not input."""
    return {
        "lt": actual < expected,
        "lte": actual <= expected,
        "gt": actual > expected,
        "gte": actual >= expected,
        "eq": actual == expected,
    }[operator]


# ORM rows keep conditions as JSON with the blueprint's own key names, while the
# validator works on dataclasses that use the schema names. This is the only
# place the two vocabularies meet.
_JSON_KEYS = {"metric_id": "metric_key"}


def _read(condition: Condition | dict[str, object], name: str) -> Any:
    """Conditions arrive either as dataclasses (validator) or as JSON dicts (ORM rows)."""
    if not isinstance(condition, dict):
        return getattr(condition, name)
    if name in condition:
        return condition[name]
    return condition[_JSON_KEYS[name]]


def conditions_all_match(
    conditions: Iterable[Condition | dict[str, object]], values: dict[str, int]
) -> bool:
    """True when every condition holds for the given metric values."""
    return all(_holds(condition, values) for condition in conditions)


def _holds(condition: Condition | dict[str, object], values: dict[str, int]) -> bool:
    metric_key = str(_read(condition, "metric_id"))
    if metric_key not in values:
        # 条件引用了已经不存在的指标（数据被手改、或蓝图被改名）：
        # 当作「条件不成立」，让上层的「没有任何结局匹配」来处理，别在玩到一半崩。
        return False
    return condition_matches(str(_read(condition, "operator")), values[metric_key], int(_read(condition, "value")))


def clamp_metric(value: int) -> int:
    """Keep a metric inside the range the database CHECK enforces.

    Without this the first choice that pushes a metric past 100 fails the
    INSERT instead of being clamped, which would break play mid-story.
    """
    return max(METRIC_MIN, min(METRIC_MAX, value))
