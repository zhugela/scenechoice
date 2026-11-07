import pytest
from pydantic import ValidationError

from app.schemas.story_blueprint import StoryBlueprint
from tests.blueprint_factory import valid_blueprint_data


@pytest.mark.parametrize("episode_count", [3, 5])
def test_blueprint_schema_accepts_supported_lengths(episode_count: int) -> None:
    blueprint = StoryBlueprint.model_validate(valid_blueprint_data(episode_count))
    assert blueprint.episode_count == episode_count
    assert len(blueprint.metrics) == 2


def test_blueprint_schema_rejects_metric_out_of_range() -> None:
    data = valid_blueprint_data()
    data["metrics"][0]["initial_value"] = 101
    with pytest.raises(ValidationError):
        StoryBlueprint.model_validate(data)


def test_blueprint_schema_rejects_more_than_two_choices() -> None:
    data = valid_blueprint_data()
    data["episodes"][0]["choices"].append(data["episodes"][0]["choices"][0])
    with pytest.raises(ValidationError):
        StoryBlueprint.model_validate(data)


@pytest.mark.parametrize("delta", [-30, 30])
def test_metric_effect_accepts_boundary_delta(delta: int) -> None:
    data = valid_blueprint_data()
    data["episodes"][0]["choices"][0]["effects"] = [{"metric_id": "reputation", "delta": delta}]
    blueprint = StoryBlueprint.model_validate(data)
    assert blueprint.episodes[0].choices[0].effects[0].delta == delta


@pytest.mark.parametrize("delta", [-31, 31])
def test_metric_effect_rejects_delta_over_limit(delta: int) -> None:
    data = valid_blueprint_data()
    data["episodes"][0]["choices"][0]["effects"] = [{"metric_id": "reputation", "delta": delta}]
    with pytest.raises(ValidationError):
        StoryBlueprint.model_validate(data)


@pytest.mark.parametrize("value", [0, 100])
def test_metric_initial_value_accepts_boundaries(value: int) -> None:
    data = valid_blueprint_data()
    data["metrics"][0]["initial_value"] = value
    assert StoryBlueprint.model_validate(data).metrics[0].initial_value == value


@pytest.mark.parametrize("value", [-1, 101])
def test_metric_initial_value_rejects_out_of_range(value: int) -> None:
    data = valid_blueprint_data()
    data["metrics"][0]["initial_value"] = value
    with pytest.raises(ValidationError):
        StoryBlueprint.model_validate(data)


def make_character(character_id: str) -> dict:
    return {
        "id": character_id,
        "name": "配角",
        "role": "旁观者",
        "goal": "推动真相浮出水面",
        "secret": "知道内情",
        "personality": ["谨慎"],
    }


def test_blueprint_accepts_four_characters() -> None:
    data = valid_blueprint_data()
    data["characters"].extend([make_character("ally"), make_character("producer")])
    assert len(StoryBlueprint.model_validate(data).characters) == 4


def test_blueprint_rejects_five_characters() -> None:
    data = valid_blueprint_data()
    data["characters"].extend(
        [make_character("ally"), make_character("producer"), make_character("viewer")]
    )
    with pytest.raises(ValidationError):
        StoryBlueprint.model_validate(data)
