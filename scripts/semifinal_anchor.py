"""Execute the preregistered 5.8 GHz meander-renderer release gate."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from yaf_ai.exploration.semifinal_anchor import (
    SEMIFINAL_ANCHOR_RUN_ID,
    run_semifinal_anchor,
)


def main() -> int:
    """Run the all-or-nothing real-solver certificate and print its gates."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--run-id", default=SEMIFINAL_ANCHOR_RUN_ID)
    args = parser.parse_args()
    os.environ["YAF_NO_FALLBACK"] = "1"
    summary = asyncio.run(run_semifinal_anchor(args.repo_root.resolve(), args.run_id))
    decision = summary.decision
    cross = decision.cross_solver_decision
    print(f"run_id={summary.run_id}")
    print(f"geometry_sha256={summary.geometry_hash}")
    for label, result in (
        ("openems_1x", summary.openems_1x),
        ("openems_2x", summary.openems_2x),
    ):
        mesh = result.mesh
        print(
            f"{label}: lines={mesh.x.line_count}/{mesh.y.line_count}/"
            f"{mesh.z.line_count} cells={mesh.total_cells} "
            f"min_cell_m={min(mesh.x.minimum_cell_size_m, mesh.y.minimum_cell_size_m, mesh.z.minimum_cell_size_m):.9g} "
            f"max_cell_m={max(mesh.x.maximum_cell_size_m, mesh.y.maximum_cell_size_m, mesh.z.maximum_cell_size_m):.9g} "
            f"peak_memory_mb={result.peak_process_tree_memory_mb:.3f} "
            f"elapsed_s={result.elapsed_seconds:.3f}"
        )
    print(
        "openems_shift="
        f"{decision.openems_resonance_shift!r} "
        f"converged={decision.openems_convergence_met}"
    )
    if cross is None:
        print(f"cross_solver_error={decision.cross_solver_error}")
    else:
        print(
            f"cross_solver_gap={cross.resonance_relative_difference:.9f} "
            f"pearson={cross.curve_pearson_correlation:.9f} "
            f"verdict={cross.verdict}"
        )
    print(f"anchor_released={decision.anchor_released}")
    return 0 if decision.anchor_released else 1


if __name__ == "__main__":
    raise SystemExit(main())
