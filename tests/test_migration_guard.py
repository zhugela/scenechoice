"""Guard: the ORM models and the migration chain must not drift apart.

``alembic check`` autogenerates against the live schema and fails when a model
change has no matching migration. Until this test existed the check was only
ever run by hand, so a model edit without a migration could reach CI green and
only fail on a real deployment.

The test owns a throwaway database: upgrade it to head, then ask Alembic
whether the models would need anything more. It never touches the developer's
``scenechoice.db``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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


def test_alembic_check_reports_no_pending_migration(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'migration-guard.db').as_posix()}"

    upgrade = _run_alembic(database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    check = _run_alembic(database_url, "check")

    output = check.stdout + check.stderr
    assert check.returncode == 0, output
    assert "No new upgrade operations detected" in output
