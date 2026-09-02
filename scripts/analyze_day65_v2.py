"""Generate the complete source-backed Day 6.5 v2 hunt analysis."""

from __future__ import annotations

import sys
from pathlib import Path

from yaf_ai.analysis.day65_v2 import write_day65_v2_analysis
from yaf_ai.exploration.cross_check import CrossCheckError


def main() -> int:
    """Write machine/human reports and all candidate figures."""

    repo_root = Path(__file__).resolve().parents[1]
    try:
        summary = write_day65_v2_analysis(repo_root)
    except (CrossCheckError, OSError, ValueError) as error:
        print(f"analyze_day65_v2: {error}", file=sys.stderr)
        return 1
    for aggregate in summary.aggregates:
        print(
            f"{aggregate.agent}: mean={aggregate.mean_best_base_score:.9f} "
            f"sd={aggregate.sample_standard_deviation:.9f} "
            f"valid_both={aggregate.valid_both_band_winners}/3"
        )
    print(f"final_verdict={summary.final_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
