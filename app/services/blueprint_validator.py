from dataclasses import dataclass
from itertools import product

from app.schemas.story_blueprint import EndingBlueprint, StoryBlueprint


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def as_prompt_line(self) -> str:
        return f"{self.path}: {self.message}"


def _duplicates(values: list[str]) -> set[str]:
    return {value for value in values if values.count(value) > 1}


def _condition_matches(operator: str, actual: int, expected: int) -> bool:
    return {
        "lt": actual < expected,
        "lte": actual <= expected,
        "gt": actual > expected,
        "gte": actual >= expected,
        "eq": actual == expected,
    }[operator]


def _ending_reachable(ending: EndingBlueprint, metric_ids: list[str]) -> bool:
    for values in product(range(101), repeat=len(metric_ids)):
        state = dict(zip(metric_ids, values, strict=True))
        if all(
            _condition_matches(condition.operator, state[condition.metric_id], condition.value)
            for condition in ending.conditions
        ):
            return True
    return False


def _ending_condition_signature(ending: EndingBlueprint) -> tuple[tuple[str, str, int], ...]:
    # Labels alone cannot distinguish endings whose executable rules are identical.
    return tuple(
        sorted(
            {
                (condition.metric_id, condition.operator, condition.value)
                for condition in ending.conditions
            }
        )
    )


def _ending_reaches_value_band(
    ending: EndingBlueprint, metric_ids: list[str], band: range
) -> bool:
    # 阈值待产品确认：产品尚未定义 low/high 的精确边界，暂以 0..100 的中点为保守边界。
    # The band is reachable when at least one constrained metric can occupy it.
    for metric_id in metric_ids:
        metric_conditions = [
            condition for condition in ending.conditions if condition.metric_id == metric_id
        ]
        if not metric_conditions:
            continue
        if any(
            all(
                _condition_matches(condition.operator, actual, condition.value)
                for condition in metric_conditions
            )
            for actual in band
        ):
            return True
    return False


class BlueprintValidator:
    def validate(self, blueprint: StoryBlueprint) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        character_ids = [item.id for item in blueprint.characters]
        metric_ids = [item.id for item in blueprint.metrics]
        choice_ids = [choice.id for episode in blueprint.episodes for choice in episode.choices]
        ending_ids = [item.id for item in blueprint.endings]

        for label, values in (
            ("characters", character_ids),
            ("metrics", metric_ids),
            ("choices", choice_ids),
            ("endings", ending_ids),
        ):
            if duplicates := _duplicates(values):
                issues.append(ValidationIssue(label, f"duplicate ids: {sorted(duplicates)}"))

        if len(blueprint.episodes) != blueprint.episode_count:
            issues.append(ValidationIssue("episodes", "count must equal episode_count"))
        expected_numbers = list(range(1, blueprint.episode_count + 1))
        if [item.number for item in blueprint.episodes] != expected_numbers:
            issues.append(ValidationIssue("episodes.number", f"must be {expected_numbers}"))

        known_characters = set(character_ids)
        known_metrics = set(metric_ids)
        for episode_index, episode in enumerate(blueprint.episodes):
            path = f"episodes.{episode_index}"
            unknown_characters = set(episode.character_ids) - known_characters
            if unknown_characters:
                issues.append(ValidationIssue(f"{path}.character_ids", f"unknown ids: {sorted(unknown_characters)}"))
            if duplicated_characters := _duplicates(episode.character_ids):
                issues.append(ValidationIssue(f"{path}.character_ids", f"duplicate ids: {sorted(duplicated_characters)}"))
            if episode_index < len(blueprint.episodes) - 1:
                if not episode.cliffhanger or not episode.cliffhanger.strip():
                    issues.append(ValidationIssue(f"{path}.cliffhanger", "required before final episode"))
            else:
                if episode.cliffhanger and episode.cliffhanger.strip():
                    issues.append(ValidationIssue(f"{path}.cliffhanger", "final episode cannot open a new cliffhanger"))
                if not episode.resolution or not episode.resolution.strip():
                    issues.append(ValidationIssue(f"{path}.resolution", "final episode must resolve the main conflict"))

            first, second = episode.choices
            first_effects = sorted((effect.metric_id, effect.delta) for effect in first.effects)
            second_effects = sorted((effect.metric_id, effect.delta) for effect in second.effects)
            if first_effects == second_effects:
                issues.append(ValidationIssue(f"{path}.choices", "choices must lead in different directions"))
            for choice_index, choice in enumerate(episode.choices):
                effect_ids = [effect.metric_id for effect in choice.effects]
                if _duplicates(effect_ids):
                    issues.append(ValidationIssue(f"{path}.choices.{choice_index}.effects", "metric cannot be repeated"))
                if unknown := set(effect_ids) - known_metrics:
                    issues.append(ValidationIssue(f"{path}.choices.{choice_index}.effects", f"unknown metric ids: {sorted(unknown)}"))
                if not any(effect.delta != 0 for effect in choice.effects):
                    issues.append(ValidationIssue(f"{path}.choices.{choice_index}.effects", "at least one delta must be non-zero"))

        categories = {ending.category for ending in blueprint.endings}
        if categories != {"low", "high", "mixed"}:
            issues.append(ValidationIssue("endings.category", "must include low, high and mixed"))
        priorities = [ending.priority for ending in blueprint.endings]
        if _duplicates([str(value) for value in priorities]):
            issues.append(ValidationIssue("endings.priority", "priorities must be unique"))
        signatures: dict[tuple[tuple[str, str, int], ...], set[str]] = {}
        for ending in blueprint.endings:
            signatures.setdefault(_ending_condition_signature(ending), set()).add(ending.category)
        if any(len(categories_for_signature) > 1 for categories_for_signature in signatures.values()):
            issues.append(
                ValidationIssue(
                    "endings.conditions",
                    "different categories cannot share identical conditions",
                )
            )
        for index, ending in enumerate(blueprint.endings):
            if unknown := {item.metric_id for item in ending.conditions} - known_metrics:
                issues.append(ValidationIssue(f"endings.{index}.conditions", f"unknown metric ids: {sorted(unknown)}"))
                continue
            if not _ending_reachable(ending, metric_ids):
                issues.append(ValidationIssue(f"endings.{index}.conditions", "conditions are unreachable"))
                continue
            if ending.category == "low" and not _ending_reaches_value_band(
                ending, metric_ids, range(50)
            ):
                issues.append(
                    ValidationIssue(
                        f"endings.{index}.category",
                        "low ending must allow a low-value state",
                    )
                )
            if ending.category == "high" and not _ending_reaches_value_band(
                ending, metric_ids, range(50, 101)
            ):
                issues.append(
                    ValidationIssue(
                        f"endings.{index}.category",
                        "high ending must allow a high-value state",
                    )
                )
        return issues
