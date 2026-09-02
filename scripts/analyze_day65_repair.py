"""Generate the source-backed Day 6.5 repair and re-verdict report."""

from __future__ import annotations

import sys
from pathlib import Path

from yaf_ai.analysis.day65_repair import write_day65_repair_analysis
from yaf_ai.exploration.cross_check import CrossCheckError


def main() -> int:
    """Write the repair summary, report, and before/after plot."""

    repo_root = Path(__file__).resolve().parents[1]
    try:
        summary = write_day65_repair_analysis(repo_root)
    except (CrossCheckError, OSError, ValueError) as error:
        print(f"analyze_day65_repair: {error}", file=sys.stderr)
        return 1
    print(f"rotation_gate={summary.rotation.openems_release_gate_passed}")
    print(f"convergence={summary.convergence_verdict}")
    for item in summary.candidates:
        print(
            f"candidate={item.selected_design.rank} low={item.low_band_verdict} "
            f"high={item.high_band_verdict} dual={item.dual_band_verdict} "
            f"pearson={item.whole_sweep_pearson:.9f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
