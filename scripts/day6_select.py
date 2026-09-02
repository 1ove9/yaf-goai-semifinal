"""Freeze the preregistered Day 6 top-two candidates without solver calls."""

from __future__ import annotations

import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day6_cross_check import write_day6_selection


def main() -> int:
    """Write and print the deterministic source addresses."""

    repo_root = Path(__file__).resolve().parents[1]
    try:
        document = write_day6_selection(repo_root)
    except CrossCheckError as error:
        print(f"day6_select: {error}", file=sys.stderr)
        return 1
    for candidate in document.candidates:
        print(
            f"rank={candidate.rank} run={candidate.source_run_id} "
            f"step={candidate.source_step_index} score={candidate.source_score:.12f} "
            f"geometry_hash={candidate.source_geometry_hash}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
