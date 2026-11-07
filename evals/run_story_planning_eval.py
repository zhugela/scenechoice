import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.clients.deepseek import DeepSeekClient  # noqa: E402
from app.config import Settings  # noqa: E402
from app.services.story_planner import StoryPlanner  # noqa: E402


def pending_manual_review() -> dict:
    return {
        "status": "pending",
        "scores": {
            "complete_arc": None,
            "theme_relevant_metrics": None,
            "meaningful_choices": None,
            "distinct_endings": None,
        },
        "total": None,
        "notes": "",
    }


async def evaluate_cases(planner, cases: list[dict], episode_count: int, model: str) -> dict:
    results = []
    for case in cases:
        try:
            result = await planner.plan(case["inspiration"], episode_count)
            results.append(
                {
                    "id": case["id"],
                    "genre": case["genre"],
                    "inspiration": case["inspiration"],
                    "structural_passed": True,
                    "attempts": result.attempts,
                    "duration_ms": result.duration_ms,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "blueprint": result.blueprint.model_dump(mode="json"),
                    "manual_review": pending_manual_review(),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": case["id"],
                    "genre": case["genre"],
                    "inspiration": case["inspiration"],
                    "structural_passed": False,
                    "error_type": type(exc).__name__,
                    "failure_issues": list(getattr(exc, "issues", [])),
                    "manual_review": pending_manual_review(),
                }
            )
    passed = sum(item["structural_passed"] for item in results)
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "episode_count": episode_count,
        "structural_gate": {
            "passed": passed,
            "total": len(results),
            "threshold": 16,
            "gate_passed": passed >= 16,
        },
        "manual_review_status": "pending",
        "results": results,
    }


async def run(
    episode_count: int,
    *,
    settings: Settings | None = None,
    planner=None,
    cases_path: Path | None = None,
    output_dir: Path | None = None,
) -> int:
    settings = settings or Settings()
    if settings.deepseek_api_key is None or not settings.deepseek_api_key.get_secret_value().strip():
        print("SCENECHOICE_DEEPSEEK_API_KEY is not configured; live evaluation was not run.")
        return 2
    cases_path = cases_path or ROOT / "evals" / "story_planning_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if planner is None:
        client = DeepSeekClient(
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout=settings.deepseek_timeout_seconds,
            max_tokens=settings.deepseek_max_tokens,
        )
        planner = StoryPlanner(client, max_attempts=settings.story_planning_max_attempts)
    report = await evaluate_cases(planner, cases, episode_count, settings.deepseek_model)
    output_dir = output_dir or ROOT / "evals" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"story-planning-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    gate = report["structural_gate"]
    print(f"Story planning evaluation: {gate['passed']}/{gate['total']}; report={report_path}")
    return 0 if gate["gate_passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, choices=[3, 5], default=3)
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(run(arguments.episodes)))
