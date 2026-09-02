"""Build or execute the terminal 5.8 GHz rod-renderer anchor r2."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from yaf_ai.exploration.semifinal_rod_anchor_r2 import (
    ROD_R2_RUN_ID,
    RodR2AnchorSummary,
    RodR2ExecutionFailureSummary,
    RodR2RepairNotConfirmedSummary,
    RodR2RunSummary,
    run_rod_anchor_r2,
    write_rod_r2_build_only_disclosure,
)


def _print_build_only(repo_root: Path) -> None:
    disclosure = write_rod_r2_build_only_disclosure(repo_root)
    print(f"run_id={ROD_R2_RUN_ID}")
    print(f"geometry_sha256={disclosure.geometry_hash}")
    print(
        "official_add_lumped_port_source_sha256="
        f"{disclosure.official_add_lumped_port_source_sha256}"
    )
    diagnostic = disclosure.diagnostic_xml
    print(
        "diagnostic_xml: "
        f"legacy_full={diagnostic.legacy_full_xml_sha256} "
        f"repaired_full={diagnostic.repaired_full_xml_sha256} "
        f"legacy_10_step={diagnostic.legacy_diagnostic_xml_sha256} "
        f"repaired_10_step={diagnostic.repaired_diagnostic_xml_sha256}"
    )
    for row, identity in zip(disclosure.refinements, disclosure.xml_identities, strict=True):
        mesh = row.mesh
        print(
            f"rod_{row.refinement:g}x: "
            f"lines={mesh.x.line_count}/{mesh.y.line_count}/{mesh.z.line_count} "
            f"cells={mesh.total_cells} "
            f"max_steps={row.maximum_timesteps} "
            f"legacy_xml={identity.legacy_xml_sha256} "
            f"repaired_xml={identity.repaired_xml_sha256}"
        )


def _print_repair(summary: RodR2RunSummary) -> None:
    repair = summary.repair_diagnostic
    for execution in (repair.legacy_a, repair.repaired_b):
        print(
            f"diagnostic_{execution.label}: "
            f"exit={execution.exit_code!r} normal={execution.normal_exit} "
            f"elapsed_s={execution.elapsed_seconds:.3f} "
            f"voltage_exists={execution.voltage_probe.exists} "
            f"voltage_samples={execution.voltage_probe.parseable_sample_count} "
            f"current_exists={execution.current_probe.exists} "
            f"current_samples={execution.current_probe.parseable_sample_count}"
        )
    print(f"repair_gate_passed={repair.gate_passed}")
    print(f"repair_failure_reasons={repair.failure_reasons!r}")


def _print_success(summary: RodR2AnchorSummary) -> None:
    print(f"run_id={summary.run_id}")
    _print_repair(summary)
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
        print(
            f"{label}: f_res_hz={result.curve.resonance_frequency_hz:.0f} "
            f"s11_db={result.curve.resonance_s11_db:.9f} "
            f"cells={result.mesh.total_cells} "
            f"terminated_by={result.termination.terminated_by} "
            f"peak_memory_mb={result.peak_process_tree_memory_mb:.3f} "
            f"elapsed_s={result.elapsed_seconds:.3f}"
        )
    decision = summary.decision
    print(f"openems_4x_to_8x_shift={decision.openems_4x_to_8x_resonance_shift!r}")
    cross = decision.cross_solver_decision
    if cross is None:
        print(f"cross_solver_error={decision.cross_solver_error!r}")
    else:
        print(
            f"cross_solver_gap={cross.resonance_relative_difference:.9f} "
            f"pearson={cross.curve_pearson_correlation:.9f}"
        )
    print(f"verdict={decision.verdict}")
    print(f"anchor_released={decision.anchor_released}")


def main() -> int:
    """Build without solving, or run the fixed preregistered r2 sequence."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.build_only:
        _print_build_only(repo_root)
        return 0
    os.environ["YAF_NO_FALLBACK"] = "1"
    summary = asyncio.run(run_rod_anchor_r2(repo_root))
    if isinstance(summary, RodR2RepairNotConfirmedSummary):
        print(f"run_id={summary.run_id}")
        _print_repair(summary)
        print("result_status=repair_not_confirmed")
        return 1
    if isinstance(summary, RodR2ExecutionFailureSummary):
        print(f"run_id={summary.run_id}")
        _print_repair(summary)
        print("result_status=execution_failed")
        print(f"failure_type={summary.failure.failure_type}")
        print(f"failure_refinement={summary.failure.refinement!r}")
        print(f"failure_message={summary.failure.message}")
        return 1
    _print_success(summary)
    return 0 if summary.decision.anchor_released else 1


if __name__ == "__main__":
    raise SystemExit(main())
