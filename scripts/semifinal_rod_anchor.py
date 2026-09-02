"""Build or execute the bounded 5.8 GHz resolved-rod anchor r1."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from yaf_ai.exploration.semifinal_rod_anchor import (
    ROD_RUN_ID,
    RodAnchorFailureSummary,
    RodAnchorSummary,
    run_rod_anchor,
    write_build_only_disclosure,
)


def _print_build_only(repo_root: Path) -> None:
    disclosure = write_build_only_disclosure(repo_root)
    print(f"legacy_xml_sha256={disclosure.legacy_xml_sha256}")
    print(f"legacy_dt_proxy_s={disclosure.legacy_dt_proxy_seconds:.12g}")
    print(f"target_physical_time_s={disclosure.target_physical_time_seconds:.12g}")
    for row in disclosure.refinements:
        mesh = row.mesh
        print(
            f"rod_{row.refinement:g}x: "
            f"lines={mesh.x.line_count}/{mesh.y.line_count}/{mesh.z.line_count} "
            f"cells={mesh.total_cells} "
            f"min_m={row.per_axis_minimum_cell_size_m} "
            f"max_m={row.per_axis_maximum_cell_size_m} "
            f"dt_proxy_s={row.dt_proxy_seconds:.12g} "
            f"max_steps={row.maximum_timesteps} "
            f"cell_steps={row.cell_timesteps}"
        )


def _print_success(summary: RodAnchorSummary) -> None:
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
    ):
        mesh = result.mesh
        termination = result.termination
        print(
            f"{label}: f_res_hz={result.curve.resonance_frequency_hz:.0f} "
            f"s11_db={result.curve.resonance_s11_db:.9f} "
            f"lines={mesh.x.line_count}/{mesh.y.line_count}/{mesh.z.line_count} "
            f"cells={mesh.total_cells} max_steps={result.maximum_timesteps} "
            f"executed_steps={termination.executed_timesteps!r} "
            f"real_dt_s={termination.openems_timestep_seconds!r} "
            f"dt_proxy_s={termination.dt_proxy_seconds:.12g} "
            f"terminated_by={termination.terminated_by} "
            f"peak_memory_mb={result.peak_process_tree_memory_mb:.3f} "
            f"elapsed_s={result.elapsed_seconds:.3f}"
        )
    decision = summary.decision
    print(
        "openems_4x_to_8x_shift="
        f"{decision.openems_4x_to_8x_resonance_shift!r} "
        f"converged={decision.openems_convergence_met}"
    )
    cross = decision.cross_solver_decision
    if cross is None:
        print(f"cross_solver_error={decision.cross_solver_error!r}")
    else:
        print(
            f"cross_solver_gap={cross.resonance_relative_difference:.9f} "
            f"pearson={cross.curve_pearson_correlation:.9f} "
            f"protocol_verdict={cross.verdict}"
        )
    print(f"invalid_resonance={decision.invalid_resonance!r}")
    print(f"verdict={decision.verdict}")
    print(f"anchor_released={decision.anchor_released}")


def main() -> int:
    """Build without solving or execute the frozen all-or-nothing study."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--run-id", default=ROD_RUN_ID)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.build_only:
        _print_build_only(repo_root)
        return 0
    os.environ["YAF_NO_FALLBACK"] = "1"
    summary = asyncio.run(run_rod_anchor(repo_root, args.run_id))
    if isinstance(summary, RodAnchorFailureSummary):
        print(f"run_id={summary.run_id}")
        print("result_status=execution_failed")
        print(f"failure_type={summary.failure.failure_type}")
        print(f"failure_refinement={summary.failure.refinement!r}")
        print(f"failure_message={summary.failure.message}")
        return 1
    _print_success(summary)
    return 0 if summary.decision.anchor_released else 1


if __name__ == "__main__":
    raise SystemExit(main())
