"""Evidence-only analysis for the final patch convergence and cross-check."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

import matplotlib
from pydantic import BaseModel, ValidationError

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from yaf_ai.exploration.cross_check import CrossCheckError, CrossCheckRunSummary
from yaf_ai.exploration.cross_check_v2 import ConvergenceRunSummary
from yaf_ai.exploration.day5_wire_convergence import Day5ConvergenceSummary
from yaf_ai.exploration.patch_final_convergence import (
    ANALYSIS_ID,
    NEC2GridRunSummary,
    OpenEMSRefinementRunSummary,
    PatchConvergenceSeries,
)
from yaf_ai.exploration.patch_final_protocol import (
    SOURCE_CONVERGENCE_RUN_ID,
    SOURCE_CROSSCHECK_RUN_ID,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load patch analysis evidence {path}: {error}") from error


def build_patch_convergence_series(repo_root: Path) -> PatchConvergenceSeries:
    """Rebuild combined state from version-controlled evidence only."""

    runs = repo_root / "artifacts" / "runs"
    openems = [
        _load(
            runs / f"{ANALYSIS_ID}-openems-2x" / "summary.json",
            OpenEMSRefinementRunSummary,
        )
    ]
    open4_path = runs / f"{ANALYSIS_ID}-openems-4x" / "summary.json"
    if open4_path.is_file():
        openems.append(_load(open4_path, OpenEMSRefinementRunSummary))
    nec2 = []
    for grid in (32, 36, 44):
        path = runs / f"{ANALYSIS_ID}-nec2-grid{grid}" / "summary.json"
        if path.is_file():
            nec2.append(_load(path, NEC2GridRunSummary))
    if not nec2:
        raise CrossCheckError("final patch analysis has no new NEC2 grid")
    selected_openems = next(
        (item.refinement for item in reversed(openems) if item.action == "selected"),
        None,
    )
    return PatchConvergenceSeries(
        openems_runs=tuple(openems),
        nec2_runs=tuple(nec2),
        selected_openems_refinement=selected_openems,
        selected_nec2_grid=nec2[-1].point.grid_intervals,
    )


def _baseline(
    repo_root: Path,
) -> tuple[CrossCheckRunSummary, ConvergenceRunSummary, Day5ConvergenceSummary]:
    runs = repo_root / "artifacts" / "runs"
    return (
        _load(
            runs / SOURCE_CROSSCHECK_RUN_ID / "summary.json", CrossCheckRunSummary
        ),
        _load(
            runs / SOURCE_CONVERGENCE_RUN_ID / "summary.json", ConvergenceRunSummary
        ),
        _load(
            runs / "day5-wire-v6r2-convergence-top1" / "summary.json",
            Day5ConvergenceSummary,
        ),
    )


def _convergence_report(
    series: PatchConvergenceSeries,
    source: CrossCheckRunSummary,
    prior: ConvergenceRunSummary,
    wire: Day5ConvergenceSummary,
) -> str:
    if series.selected_openems_refinement is None:
        raise CrossCheckError("openEMS did not reach its frozen convergence gate")
    open_rows = [
        f"| 1x | {source.openems.resonance_frequency_hz / 1e9:.6f} | "
        f"{source.openems.resonance_s11_db:.6f} | n/a (archived) | "
        f"{source.openems.simulation_time_seconds:.3f} | baseline | "
        f"`{SOURCE_CROSSCHECK_RUN_ID}` |"
    ]
    for open_stage in series.openems_runs:
        open_rows.append(
            f"| {open_stage.refinement:g}x | "
            f"{open_stage.curve.resonance_frequency_hz / 1e9:.6f} | "
            f"{open_stage.curve.resonance_s11_db:.6f} | "
            f"{open_stage.predicted_seconds:.3f} | "
            f"{open_stage.actual_wall_seconds:.3f} | "
            f"{open_stage.adjacent_resonance_shift:.6%} / "
            f"{open_stage.action} | `{open_stage.run_id}` |"
        )
    prior_rows = [
        f"| {point.grid_intervals} | {point.segment_count} | "
        f"{point.nec2_resonance_frequency_hz / 1e9:.6f} | "
        f"{point.curve.resonance_s11_db:.6f} | {point.resonance_relative_gap:.6%} | "
        f"n/a | {point.solve_time_seconds:.3f} | n/a | n/a | "
        f"`{SOURCE_CONVERGENCE_RUN_ID}` |"
        for point in prior.points
    ]
    new_rows = []
    for grid_stage in series.nec2_runs:
        prediction = grid_stage.resource_prediction
        new_rows.append(
            f"| {grid_stage.point.grid_intervals} | "
            f"{grid_stage.point.segment_count} | "
            f"{grid_stage.point.nec2_resonance_frequency_hz / 1e9:.6f} | "
            f"{grid_stage.point.curve.resonance_s11_db:.6f} | "
            f"{grid_stage.point.resonance_relative_gap:.6%} | "
            f"{prediction.predicted_seconds:.3f} | "
            f"{grid_stage.actual_wall_seconds:.3f} | "
            f"{prediction.predicted_matrix_bytes / 2**20:.3f} | "
            f"{grid_stage.extrapolation.estimated_grid_for_five_percent} | "
            f"`{grid_stage.run_id}` |"
        )
    patch_points = (*prior.points, *(item.point for item in series.nec2_runs))
    patch_monotonic = all(
        left.resonance_relative_gap >= right.resonance_relative_gap
        for left, right in zip(patch_points, patch_points[1:], strict=False)
    )
    wire_monotonic = all(
        left >= right
        for left, right in zip(
            wire.nec2_to_refined_openems_gaps,
            wire.nec2_to_refined_openems_gaps[1:],
            strict=False,
        )
    )
    patch_sequence = " -> ".join(
        f"g{point.grid_intervals}:{point.resonance_relative_gap:.3%}"
        for point in patch_points
    )
    wire_sequence = " -> ".join(
        f"lambda/{density}:{gap:.3%}"
        for density, gap in zip(
            (20, 40, 80), wire.nec2_to_refined_openems_gaps, strict=True
        )
    )
    final = series.nec2_runs[-1]
    return "\n".join(
        [
            "# Day 5-2 patch instrument convergence",
            "",
            "The candidate, air transformation, 51 samples, and 4.098041023--6.830068372 "
            "GHz sweep are frozen in `docs/patch-crosscheck-final-execution-note.md`.",
            "",
            "## openEMS self-check",
            "",
            "| refinement | f_res GHz | S11 dB | predicted s | actual wall s | shift/action | source |",
            "|---:|---:|---:|---:|---:|---|---|",
            *open_rows,
            "",
            f"Selected openEMS refinement: {series.selected_openems_refinement:g}x. The final "
            "adjacent shift is at or below the frozen 3% threshold.",
            "",
            "## Patch NEC2 ladder",
            "",
            "| grid | segments | f_res GHz | S11 dB | gap to Day3 openEMS | predicted s | actual wall s | matrix MiB | grid for 5% | source |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            *prior_rows,
            *new_rows,
            "",
            f"The fixed-reference patch gap sequence is `{patch_sequence}`; monotonically "
            f"non-increasing: {patch_monotonic}. Grid 44 remains above 5%, so the current "
            f"power-law roadmap is grid {final.extrapolation.estimated_grid_for_five_percent}. "
            f"The wire-reference Pearson roadmap is grid "
            f"{final.extrapolation.estimated_grid_for_pearson} and is descriptive only.",
            "",
            "## Two native-geometry convergence studies",
            "",
            "| geometry study | fixed independent reference | resolution/gap sequence | monotonic non-increasing |",
            "|---|---|---|---|",
            f"| patch air variant | archived openEMS 1x (`{SOURCE_CROSSCHECK_RUN_ID}`) | "
            f"{patch_sequence} | {patch_monotonic} |",
            f"| meander wire | openEMS 2x (`{wire.run_id}`) | {wire_sequence} | "
            f"{wire_monotonic} |",
            "",
            "These fixed-reference studies show the same discretization-driven narrowing in "
            "two geometry classes. This statement does not conceal the later Day 5-1b "
            "re-reference to converged openEMS 8x, whose final NEC2 gap sequence was not "
            "strictly monotonic; that separate attribution remains unchanged.",
            "",
            "![Patch and wire fixed-reference convergence](convergence-comparison.png)",
        ]
    )


def _plot(
    output: Path,
    series: PatchConvergenceSeries,
    prior: ConvergenceRunSummary,
    wire: Day5ConvergenceSummary,
) -> None:
    patch_points = (*prior.points, *(item.point for item in series.nec2_runs))
    figure, axes = plt.subplots(1, 2, figsize=(11.2, 4.5))
    axes[0].plot(
        [item.grid_intervals for item in patch_points],
        [100.0 * item.resonance_relative_gap for item in patch_points],
        marker="o",
        color="#7b2cbf",
    )
    axes[0].axhline(5.0, color="black", linestyle="--", label="5% threshold")
    axes[0].set_title("Patch air variant vs fixed openEMS 1x")
    axes[0].set_xlabel("NEC2 grid intervals")
    axes[0].set_ylabel("resonance gap (%)")
    axes[0].set_xticks([item.grid_intervals for item in patch_points])
    axes[0].grid(alpha=0.25)
    axes[0].legend()
    axes[1].plot(
        [20, 40, 80],
        [100.0 * gap for gap in wire.nec2_to_refined_openems_gaps],
        marker="o",
        color="#0077b6",
    )
    axes[1].axhline(5.0, color="black", linestyle="--", label="5% threshold")
    axes[1].set_title("Meander wire vs fixed openEMS 2x")
    axes[1].set_xlabel("NEC2 segments per wavelength")
    axes[1].set_ylabel("resonance gap (%)")
    axes[1].set_xticks([20, 40, 80])
    axes[1].grid(alpha=0.25)
    axes[1].legend()
    figure.suptitle("Fixed-reference discretization convergence across geometry classes")
    figure.tight_layout()
    figure.savefig(output / "convergence-comparison.png", dpi=180)
    plt.close(figure)


def write_patch_convergence_analysis(repo_root: Path) -> PatchConvergenceSeries:
    """Write machine-readable state, convergence table, and comparison plot."""

    series = build_patch_convergence_series(repo_root)
    source, prior, wire = _baseline(repo_root)
    output = repo_root / "artifacts" / "analysis" / ANALYSIS_ID
    output.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            series.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    temporary = output / "convergence-summary.json.tmp"
    temporary.write_bytes(payload)
    os.replace(temporary, output / "convergence-summary.json")
    report = (_convergence_report(series, source, prior, wire) + "\n").encode(
        "utf-8"
    )
    temporary_report = output / "convergence.md.tmp"
    temporary_report.write_bytes(report)
    os.replace(temporary_report, output / "convergence.md")
    _plot(output, series, prior, wire)
    return series
