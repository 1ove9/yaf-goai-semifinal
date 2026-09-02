"""Generate the Day 6 free-form evidence report and figures."""

from __future__ import annotations

import sys
from pathlib import Path

from yaf_ai.analysis.day6 import write_day6_analysis
from yaf_ai.exploration.cross_check import CrossCheckError


def main() -> int:
    """Build all source-addressed Day 6 analysis artifacts."""

    repo_root = Path(__file__).resolve().parents[1]
    try:
        summary = write_day6_analysis(repo_root)
    except (CrossCheckError, OSError, ValueError) as error:
        print(f"analyze_day6: {error}", file=sys.stderr)
        return 1
    print(f"verdict={summary.final_verdict} rows={len(summary.rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
