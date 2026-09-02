"""Build the Day 5-2 convergence evidence from archived solver runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_final_analysis import (
    write_patch_convergence_analysis,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        series = write_patch_convergence_analysis(
            Path(__file__).resolve().parents[1]
        )
    except CrossCheckError as error:
        print(f"analyze_patch_convergence: {error}", file=sys.stderr)
        return 1
    if series.selected_openems_refinement is None:
        print("analyze_patch_convergence: openEMS is not converged", file=sys.stderr)
        return 1
    print(
        f"openems={series.selected_openems_refinement:g}x "
        f"nec2_grid={series.selected_nec2_grid} "
        f"grid_for_5pct="
        f"{series.nec2_runs[-1].extrapolation.estimated_grid_for_five_percent}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
