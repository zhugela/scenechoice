import pytest

from app.schemas.story_blueprint import StoryBlueprint
from app.services.blueprint_validator import BlueprintValidator
from tests.blueprint_factory import valid_blueprint_data


def validate(data: dict) -> list[str]:
    blueprint = StoryBlueprint.model_validate(data)
    return [f"{issue.path}: {issue.message}" for issue in BlueprintValidator().validate(blueprint)]


def test_valid_blueprint_has_no_business_issues() -> None:
    assert validate(valid_blueprint_data()) == []


def test_validator_reports_duplicate_and_unknown_ids() -> None:
    data = valid_blueprint_data()
    data["characters"][1]["id"] = "anchor"
    data["episodes"][0]["character_ids"] = ["ghost"]
    issues = validate(data)
    assert any("duplicate ids" in issue for issue in issues)
    assert any("unknown ids" in issue for issue in issues)


def test_validator_reports_bad_episode_flow_and_same_choices() -> None:
    data = valid_blueprint_data()
    data["episodes"][0]["number"] = 2
    data["episodes"][0]["cliffhanger"] = None
    data["episodes"][0]["choices"][1] = data["episodes"][0]["choices"][0] | {"id": "different_id"}
    data["episodes"][-1]["cliffhanger"] = "又有新危机"
    data["episodes"][-1]["resolution"] = None
    issues = validate(data)
    assert any("must be [1, 2, 3]" in issue for issue in issues)
    assert any("required before final" in issue for issue in issues)
    assert any("different directions" in issue for issue in issues)
    assert any("cannot open" in issue for issue in issues)
    assert any("must resolve" in issue for issue in issues)


def test_validator_reports_unreachable_ending() -> None:
    data = valid_blueprint_data()
    data["endings"][2]["conditions"] = [
        {"metric_id": "reputation", "operator": "lt", "value": 20},
        {"metric_id": "reputation", "operator": "gt", "value": 80},
    ]
    assert any("unreachable" in issue for issue in validate(data))


def test_different_intent_text_cannot_hide_identical_effects() -> None:
    data = valid_blueprint_data()
    data["episodes"][0]["choices"][1]["intent"] = "完全不同的文案"
    data["episodes"][0]["choices"][1]["effects"] = data["episodes"][0]["choices"][0]["effects"]
    assert any("different directions" in issue for issue in validate(data))


def test_cross_metric_ending_conditions_can_be_reachable() -> None:
    data = valid_blueprint_data()
    data["endings"][2]["conditions"] = [
        {"metric_id": "reputation", "operator": "gte", "value": 70},
        {"metric_id": "mindset", "operator": "lte", "value": 30},
    ]
    assert validate(data) == []


def test_cross_metric_constraints_still_detect_same_metric_contradiction() -> None:
    data = valid_blueprint_data()
    data["endings"][2]["conditions"] = [
        {"metric_id": "mindset", "operator": "lt", "value": 20},
        {"metric_id": "mindset", "operator": "gt", "value": 80},
    ]
    assert any("unreachable" in issue for issue in validate(data))


def _duplicate_character_id(data: dict) -> None:
    data["characters"][1]["id"] = data["characters"][0]["id"]


def _duplicate_metric_id(data: dict) -> None:
    data["metrics"][1]["id"] = data["metrics"][0]["id"]


def _duplicate_choice_id(data: dict) -> None:
    data["episodes"][1]["choices"][0]["id"] = data["episodes"][0]["choices"][0]["id"]


def _duplicate_ending_id(data: dict) -> None:
    data["endings"][1]["id"] = data["endings"][0]["id"]


def _duplicate_ending_priority(data: dict) -> None:
    data["endings"][1]["priority"] = data["endings"][0]["priority"]


def _unknown_episode_character(data: dict) -> None:
    data["episodes"][0]["character_ids"] = ["ghost"]


def _unknown_effect_metric(data: dict) -> None:
    data["episodes"][0]["choices"][0]["effects"] = [{"metric_id": "fame", "delta": 5}]


def _unknown_ending_metric(data: dict) -> None:
    data["endings"][0]["conditions"] = [{"metric_id": "fame", "operator": "lt", "value": 30}]


def _episode_count_mismatch(data: dict) -> None:
    data["episode_count"] = 5


def _non_contiguous_numbers(data: dict) -> None:
    data["episodes"][2]["number"] = 4


def _identical_choices(data: dict) -> None:
    data["episodes"][0]["choices"][1] = {**data["episodes"][0]["choices"][0], "id": "e1_copy"}


def _missing_cliffhanger(data: dict) -> None:
    data["episodes"][0]["cliffhanger"] = None


def _final_cliffhanger(data: dict) -> None:
    data["episodes"][-1]["cliffhanger"] = "新的悬念"


def _missing_resolution(data: dict) -> None:
    data["episodes"][-1]["resolution"] = None


def _zero_delta(data: dict) -> None:
    data["episodes"][0]["choices"][0]["effects"] = [{"metric_id": "reputation", "delta": 0}]


def _unreachable_conditions(data: dict) -> None:
    data["endings"][2]["conditions"] = [
        {"metric_id": "reputation", "operator": "lt", "value": 20},
        {"metric_id": "reputation", "operator": "gt", "value": 80},
    ]


def _missing_ending_category(data: dict) -> None:
    data["endings"][1]["category"] = "low"


def _duplicate_episode_character(data: dict) -> None:
    first_id = data["characters"][0]["id"]
    data["episodes"][0]["character_ids"] = [first_id, first_id]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        pytest.param(_duplicate_character_id, "characters: duplicate ids", id="rule1-character"),
        pytest.param(_duplicate_metric_id, "metrics: duplicate ids", id="rule1-metric"),
        pytest.param(_duplicate_choice_id, "choices: duplicate ids", id="rule1-choice"),
        pytest.param(_duplicate_ending_id, "endings: duplicate ids", id="rule1-ending"),
        pytest.param(_duplicate_ending_priority, "priorities must be unique", id="rule1-priority"),
        pytest.param(_unknown_episode_character, "episodes.0.character_ids: unknown ids", id="rule2-episode-character"),
        pytest.param(_unknown_effect_metric, "episodes.0.choices.0.effects: unknown metric ids", id="rule2-effect-metric"),
        pytest.param(_unknown_ending_metric, "endings.0.conditions: unknown metric ids", id="rule2-ending-metric"),
        pytest.param(_episode_count_mismatch, "count must equal episode_count", id="rule3-count"),
        pytest.param(_non_contiguous_numbers, "episodes.number: must be [1, 2, 3]", id="rule3-numbers"),
        pytest.param(_identical_choices, "choices must lead in different directions", id="rule4-identical"),
        pytest.param(_missing_cliffhanger, "required before final", id="rule5-missing-cliffhanger"),
        pytest.param(_final_cliffhanger, "cannot open a new cliffhanger", id="rule5-final-cliffhanger"),
        pytest.param(_missing_resolution, "final episode must resolve", id="rule5-missing-resolution"),
        pytest.param(_zero_delta, "at least one delta must be non-zero", id="rule6-zero-delta"),
        pytest.param(_unreachable_conditions, "unreachable", id="rule8-unreachable"),
        pytest.param(_missing_ending_category, "must include low, high and mixed", id="rule9-categories"),
        pytest.param(
            _duplicate_episode_character,
            "episodes.0.character_ids: duplicate ids",
            id="rule10-episode-character-duplicate",
        ),
    ],
)
def test_each_business_rule_is_reported_independently(mutate, expected: str) -> None:
    data = valid_blueprint_data()
    mutate(data)
    issues = validate(data)
    assert any(expected in issue for issue in issues), issues


def test_reachability_covers_state_space_not_playable_paths() -> None:
    # 初始 50、三集最多 +12*3=86，gte 95 在玩法上到不了，但状态空间内可达。
    data = valid_blueprint_data()
    data["endings"][1]["conditions"] = [{"metric_id": "reputation", "operator": "gte", "value": 95}]
    assert validate(data) == []
