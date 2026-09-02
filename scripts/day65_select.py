"""Freeze Day 6.5 v2 top-two source addresses before cross-check output."""

from __future__ import annotations

from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day65_selection import write_day65_selection


def main() -> int:
    """Write or integrity-check the deterministic source-only selection."""

    repo_root = Path(__file__).resolve().parents[1]
    try:
        selection = write_day65_selection(repo_root)
    except (CrossCheckError, OSError, ValueError) as error:
        print(f"day65_select: {error}")
        return 1
    for candidate in selection.candidates:
        print(
            f"top{candidate.rank}: run={candidate.source_run_id} "
            f"step={candidate.source_step_index} base={candidate.source_base_score:.9f} "
            f"search={candidate.source_search_score:.9f} "
            f"valid_both={candidate.source_valid_both_bands}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
