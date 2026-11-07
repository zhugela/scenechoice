import json
import asyncio
from pathlib import Path

from pydantic import SecretStr

from app.config import Settings
from app.schemas.story_blueprint import StoryBlueprint
from app.services.story_planner import PlanningResult, StoryPlanningError
from evals.run_story_planning_eval import evaluate_cases, run
from tests.blueprint_factory import valid_blueprint_data


def test_fixed_evaluation_set_has_twenty_unique_diverse_cases() -> None:
    path = Path(__file__).parents[1] / "evals" / "story_planning_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20
    assert {"livestream", "gaming", "mystery", "workplace", "family", "emotion", "campus", "science_fiction"}.issubset({case["genre"] for case in cases})
    assert all(len(case["inspiration"]) >= 5 for case in cases)


class FakePlanner:
    async def plan(self, inspiration: str, episode_count: int) -> PlanningResult:
        return PlanningResult(
            blueprint=StoryBlueprint.model_validate(valid_blueprint_data(episode_count)),
            attempts=2,
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=200,
            duration_ms=300,
        )


def test_evaluation_report_keeps_evidence_for_manual_review() -> None:
    cases = [{"id": "case_01", "genre": "gaming", "inspiration": "主播遭遇直播事故"}]
    report = asyncio.run(evaluate_cases(FakePlanner(), cases, 3, "fake-model"))
    result = report["results"][0]

    assert report["schema_version"] == 1
    assert report["structural_gate"] == {
        "passed": 1,
        "total": 1,
        "threshold": 16,
        "gate_passed": False,
    }
    assert result["blueprint"]["title"] == "麦克风没有关"
    assert result["prompt_tokens"] == 100
    assert result["completion_tokens"] == 200
    assert result["duration_ms"] == 300
    assert result["manual_review"]["status"] == "pending"
    assert set(result["manual_review"]["scores"]) == {
        "complete_arc",
        "theme_relevant_metrics",
        "meaningful_choices",
        "distinct_endings",
    }


class FailingPlanner:
    async def plan(self, inspiration: str, episode_count: int) -> PlanningResult:
        raise StoryPlanningError(
            "story blueprint failed validation",
            attempts=3,
            issues=["episodes.0.character_ids: duplicate ids: ['anchor']"],
        )


def test_evaluation_report_keeps_failure_issues() -> None:
    cases = [{"id": "case_01", "genre": "gaming", "inspiration": "主播遭遇直播事故"}]
    report = asyncio.run(evaluate_cases(FailingPlanner(), cases, 3, "fake-model"))
    result = report["results"][0]

    assert result["structural_passed"] is False
    assert result["error_type"] == "StoryPlanningError"
    assert result["failure_issues"] == ["episodes.0.character_ids: duplicate ids: ['anchor']"]
    assert result["manual_review"]["status"] == "pending"


class ThresholdPlanner:
    def __init__(self, successful_calls: int) -> None:
        self.successful_calls = successful_calls
        self.calls = 0

    async def plan(self, inspiration: str, episode_count: int) -> PlanningResult:
        self.calls += 1
        if self.calls > self.successful_calls:
            raise StoryPlanningError("invalid", attempts=3, issues=["rule failed"])
        return await FakePlanner().plan(inspiration, episode_count)


def twenty_cases() -> list[dict]:
    return [
        {"id": f"case_{index:02d}", "genre": "gaming", "inspiration": f"故事灵感 {index}"}
        for index in range(1, 21)
    ]


def test_structural_gate_passes_at_exactly_sixteen_of_twenty() -> None:
    report = asyncio.run(evaluate_cases(ThresholdPlanner(16), twenty_cases(), 3, "fake-model"))
    assert report["structural_gate"] == {
        "passed": 16,
        "total": 20,
        "threshold": 16,
        "gate_passed": True,
    }


def test_structural_gate_fails_at_fifteen_of_twenty() -> None:
    report = asyncio.run(evaluate_cases(ThresholdPlanner(15), twenty_cases(), 3, "fake-model"))
    assert report["structural_gate"]["passed"] == 15
    assert report["structural_gate"]["gate_passed"] is False


def write_cases(path: Path) -> Path:
    path.write_text(json.dumps(twenty_cases(), ensure_ascii=False), encoding="utf-8")
    return path


def live_settings() -> Settings:
    return Settings(_env_file=None, deepseek_api_key=SecretStr("fake-key"))


def test_run_returns_zero_and_writes_report_for_passing_gate(tmp_path) -> None:
    report_dir = tmp_path / "reports"
    exit_code = asyncio.run(
        run(
            3,
            settings=live_settings(),
            planner=ThresholdPlanner(16),
            cases_path=write_cases(tmp_path / "cases.json"),
            output_dir=report_dir,
        )
    )
    reports = list(report_dir.glob("story-planning-*.json"))
    assert exit_code == 0
    assert len(reports) == 1
    assert json.loads(reports[0].read_text(encoding="utf-8"))["structural_gate"]["gate_passed"] is True


def test_run_returns_one_for_failing_gate(tmp_path) -> None:
    exit_code = asyncio.run(
        run(
            3,
            settings=live_settings(),
            planner=ThresholdPlanner(15),
            cases_path=write_cases(tmp_path / "cases.json"),
            output_dir=tmp_path / "reports",
        )
    )
    assert exit_code == 1


def test_run_returns_two_when_key_is_missing(tmp_path) -> None:
    settings = Settings(_env_file=None, deepseek_api_key=None)
    assert asyncio.run(run(3, settings=settings, output_dir=tmp_path)) == 2
