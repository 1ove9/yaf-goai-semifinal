"""Execute the bounded 5.8 GHz meander-renderer r3 certificate."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from yaf_ai.exploration.semifinal_anchor_r3 import (
    R3_RUN_ID,
    run_semifinal_anchor_r3,
)


def main() -> int:
    """Run all seven real solves and print the bounded terminal verdict."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--run-id", default=R3_RUN_ID)
    args = parser.parse_args()
    os.environ["YAF_NO_FALLBACK"] = "1"
    summary = asyncio.run(
        run_semifinal_anchor_r3(args.repo_root.resolve(), args.run_id)
    )
    print(f"run_id={summary.run_id}")
    print(f"geometry_sha256={summary.geometry_hash}")
    print(
        "nec2: "
        f"f_res_hz={summary.nec2.resonance_frequency_hz:.0f} "
        f"s11_db={summary.nec2.resonance_s11_db:.9f} "
        f"elapsed_s={summary.nec2.simulation_time_seconds:.3f}"
    )
    for label, result in (
        ("openems_1x", summary.openems_1x),
        ("openems_2x", summary.openems_2x),
        ("openems_4x", summary.openems_4x),
        ("openems_8x", summary.openems_8x),
        ("openems_16x", summary.openems_16x),
        ("openems_32x", summary.openems_32x),
    ):
        mesh = result.mesh
        minimum_cell = min(
            mesh.x.minimum_cell_size_m,
            mesh.y.minimum_cell_size_m,
            mesh.z.minimum_cell_size_m,
        )
        maximum_cell = max(
            mesh.x.maximum_cell_size_m,
            mesh.y.maximum_cell_size_m,
            mesh.z.maximum_cell_size_m,
        )
        print(
            f"{label}: f_res_hz={result.curve.resonance_frequency_hz:.0f} "
            f"s11_db={result.curve.resonance_s11_db:.9f} "
            f"lines={mesh.x.line_count}/{mesh.y.line_count}/{mesh.z.line_count} "
            f"cells={mesh.total_cells} min_cell_m={minimum_cell:.9g} "
            f"max_cell_m={maximum_cell:.9g} "
            f"peak_memory_mb={result.peak_process_tree_memory_mb:.3f} "
            f"elapsed_s={result.elapsed_seconds:.3f}"
        )
    decision = summary.decision
    print(
        "openems_16x_to_32x_shift="
        f"{decision.openems_16x_to_32x_resonance_shift!r} "
        f"converged={decision.openems_convergence_met}"
    )
    cross = decision.cross_solver_decision
    if cross is None:
        print(f"cross_solver_error={decision.cross_solver_error}")
    else:
        print(
            f"cross_solver_gap={cross.resonance_relative_difference:.9f} "
            f"pearson={cross.curve_pearson_correlation:.9f} "
            f"verdict={cross.verdict}"
        )
    richardson = summary.richardson_estimate
    print(
        f"richardson_status={richardson.status} "
        f"order={richardson.estimated_order!r} "
        f"limit_hz={richardson.estimated_limit_frequency_hz!r} "
        f"reason={richardson.reason!r}"
    )
    for row in summary.r2_reproduction:
        print(
            f"r2_reproduction_{row.refinement:g}x: "
            f"delta_f_hz={row.frequency_difference_hz:.0f} "
            f"delta_s11_db={row.s11_difference_db:.12g}"
        )
    print(f"verdict={decision.verdict}")
    print(f"anchor_released={decision.anchor_released}")
    return 0 if decision.anchor_released else 1


if __name__ == "__main__":
    raise SystemExit(main())
