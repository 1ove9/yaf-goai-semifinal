"""Archive the observed Day 6 final NEC2 300-second timeout."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day6_cross_check import record_day6_timeout_failure


def main() -> int:
    """Write and archive a no-numeric-decision failure record."""

    repo_root = Path(__file__).resolve().parents[1]
    try:
        summary = record_day6_timeout_failure(repo_root)
        subprocess.run(
            [
                sys.executable,
                str(repo_root / "scripts" / "archive_run.py"),
                summary.run_id,
                "--role",
                "other",
                "--note",
                "batch=day6-freeform candidate=top1 aborted lambda160 timeout=300s; no numeric decision",
            ],
            cwd=repo_root,
            check=True,
        )
    except (CrossCheckError, OSError, subprocess.CalledProcessError) as error:
        print(f"day6_record_timeout: {error}", file=sys.stderr)
        return 1
    print(f"{summary.run_id}: {summary.result_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
