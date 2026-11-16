import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["SCENECHOICE_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_endings_position_upgrade_keeps_existing_data_and_priority_fallback(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing.db"
    database_url = f"sqlite:///{database_path.as_posix()}"

    initial_upgrade = _run_alembic(database_url, "upgrade", "20261115_0001")
    assert initial_upgrade.returncode == 0, initial_upgrade.stderr

    engine = create_engine(database_url)
    created_at = datetime.now(UTC).isoformat()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO stories (
                    public_id, title, logline, genre, theme, episode_count,
                    status, blueprint_version, created_at, updated_at
                ) VALUES (
                    :public_id, :title, :logline, :genre, :theme, 3,
                    'ready', 1, :created_at, :created_at
                )
                """
            ),
            {
                "public_id": "00000000-0000-0000-0000-000000000001",
                "title": "旧存档",
                "logline": "升级前已经存在的故事。",
                "genre": "测试",
                "theme": "兼容",
                "created_at": created_at,
            },
        )
        for key, priority in (("comeback", 2), ("quit", 1), ("survive", 3)):
            connection.execute(
                text(
                    """
                    INSERT INTO endings (
                        story_id, key, priority, title, summary, category, conditions
                    ) VALUES (
                        1, :key, :priority, :title, :summary, 'mixed', '[]'
                    )
                    """
                ),
                {
                    "key": key,
                    "priority": priority,
                    "title": key,
                    "summary": key,
                },
            )
    engine.dispose()

    current_upgrade = _run_alembic(database_url, "upgrade", "head")
    assert current_upgrade.returncode == 0, current_upgrade.stderr

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            endings = connection.execute(
                text(
                    """
                    SELECT key, priority, position
                    FROM endings
                    ORDER BY position, priority
                    """
                )
            ).all()
    finally:
        engine.dispose()

    assert revision == "20261116_0002"
    assert endings == [
        ("quit", 1, 0),
        ("comeback", 2, 0),
        ("survive", 3, 0),
    ]
