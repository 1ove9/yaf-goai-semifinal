"""Source-backed report for the Day 6.5 renderer repair and re-verdict."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

import matplotlib
from pydantic import BaseModel, ConfigDict

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from yaf_ai.exploration.cross_check import CrossCheckError  # noqa: E402
from yaf_ai.exploration.day6_cross_check import (  # noqa: E402
    BandResonanceValidity,
    Day6CrossCheckRunSummary,
    Day6InstrumentRunSummary,
    band_validity,
)
from yaf_ai.exploration.day65 import (  # noqa: E402
    DAY65_ROTATION_RUN_ID,
    Day65RotationSummary,
)
from yaf_ai.exploration.day65_repair import (  # noqa: E402
    Day65CandidateRunSummary,
    repaired_convergence_shift,
)
from yaf_ai.exploration.freeform_wire import HIGH_BAND_HZ  # noqa: E402

REPAIR_OUTPUT = "artifacts/analysis/day65-repair"
REPAIR_CONVERGENCE_RUNS = tuple(
    f"day65-repair-openems-convergence-top1-{value}x"
    for value in ("1", "2", "4", "6")
)
REPAIR_CANDIDATE_RUNS = (
    "day65-repair-crosscheck-top1",
    "day65-repair-crosscheck-top2",
)
OLD_CANDIDATE_RUNS = (
    "day6-freeform-final-crosscheck-top1",
    "day6-freeform-final-crosscheck-top2",
)


class RepairConvergenceRow(BaseModel):
    """One archived convergence level with explicit resonance validity."""

    model_config = ConfigDict(frozen=True)

    refinement: float
    source_run_id: str
    high_band: BandResonanceValidity
    simulation_time_seconds: float
    shift_from_previous: float | None


class Day65RepairAnalysisSummary(BaseModel):
    """Complete machine-readable renderer repair report payload."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    renderer_iteration: str = "r12"
    rotation_source_run_id: str
    rotation: Day65RotationSummary
    convergence: tuple[
        RepairConvergenceRow,
        RepairConvergenceRow,
        RepairConvergenceRow,
        RepairConvergenceRow,
    ]
    convergence_verdict: str
    candidates: tuple[Day65CandidateRunSummary, Day65CandidateRunSummary]
    pre_repair_source_run_ids: tuple[str, str]
    final_dual_band_verdict: str


ModelT = TypeVar("ModelT", bound=BaseModel)


def _read_model(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CrossCheckError(f"cannot read analysis evidence {path}: {error}") from error


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def build_day65_repair_analysis(repo_root: Path) -> Day65RepairAnalysisSummary:
    """Load only archived evidence and apply the frozen reporting rules."""

    runs = repo_root / "artifacts" / "runs"
    rotation = _read_model(
        runs / DAY65_ROTATION_RUN_ID / "summary.json", Day65RotationSummary
    )
    if not rotation.openems_release_gate_passed or not rotation.nec2_control_passed:
        raise CrossCheckError("r12 rotation release gate is not passing")
    convergence_summaries = [
        _read_model(runs / run_id / "summary.json", Day6InstrumentRunSummary)
        for run_id in REPAIR_CONVERGENCE_RUNS
    ]
    convergence_rows: list[RepairConvergenceRow] = []
    previous: Day6InstrumentRunSummary | None = None
    for refinement, summary in zip(
        (1.0, 2.0, 4.0, 6.0), convergence_summaries, strict=True
    ):
        convergence_rows.append(
            RepairConvergenceRow(
                refinement=refinement,
                source_run_id=summary.run_id,
                high_band=band_validity(summary.curve, HIGH_BAND_HZ),
                simulation_time_seconds=summary.curve.simulation_time_seconds,
                shift_from_previous=(
                    None
                    if previous is None
                    else repaired_convergence_shift(previous, summary)
                ),
            )
        )
        previous = summary
    convergence_verdict = (
        "self_convergence_established"
        if any(row.shift_from_previous is not None and row.shift_from_previous <= 0.03 for row in convergence_rows)
        else "self_convergence_not_established"
    )
    candidates = tuple(
        _read_model(runs / run_id / "summary.json", Day65CandidateRunSummary)
        for run_id in REPAIR_CANDIDATE_RUNS
    )
    if len(candidates) != 2:
        raise CrossCheckError("both frozen repaired candidates are required")
    final = (
        "confirmed_dual_band_improvement"
        if any(item.discovery_verdict == "confirmed_improvement" for item in candidates)
        else "dual_band_objective_not_confirmed"
    )
    return Day65RepairAnalysisSummary(
        rotation_source_run_id=rotation.run_id,
        rotation=rotation,
        convergence=(
            convergence_rows[0],
            convergence_rows[1],
            convergence_rows[2],
            convergence_rows[3],
        ),
        convergence_verdict=convergence_verdict,
        candidates=(candidates[0], candidates[1]),
        pre_repair_source_run_ids=OLD_CANDIDATE_RUNS,
        final_dual_band_verdict=final,
    )


def _plot_before_after(
    repo_root: Path,
    output: Path,
    candidates: Sequence[Day65CandidateRunSummary],
) -> None:
    runs = repo_root / "artifacts" / "runs"
    before = [
        _read_model(runs / run_id / "summary.json", Day6CrossCheckRunSummary)
        for run_id in OLD_CANDIDATE_RUNS
    ]
    figure, axes = plt.subplots(2, 1, figsize=(10.5, 8.5), sharex=True)
    for axis, old, repaired in zip(axes, before, candidates, strict=True):
        series = (
            ("pre-repair openEMS flat curve", old.openems, "#9ca3af", "--"),
            ("repaired openEMS 6x", repaired.openems, "#d97706", "-"),
            ("NEC2 lambda/160", repaired.nec2, "#1769aa", "-"),
        )
        for label, curve, color, style in series:
            axis.plot(
                np.asarray(curve.frequency_hz) / 1e9,
                curve.s11_db,
                label=label,
                color=color,
                linestyle=style,
                linewidth=1.5,
            )
        axis.axvspan(2.40, 2.50, color="#60a5fa", alpha=0.16)
        axis.axvspan(5.725, 5.875, color="#f59e0b", alpha=0.16)
        axis.axhline(-6.0, color="black", linestyle=":", linewidth=1.0)
        axis.set_ylabel("S11 (dB)")
        axis.set_title(
            f"Frozen candidate {'A' if repaired.selected_design.rank == 1 else 'B'}: "
            f"low={repaired.low_band_verdict}, high={repaired.high_band_verdict}"
        )
        axis.grid(alpha=0.2)
        axis.legend(fontsize=8)
    axes[-1].set_xlabel("Frequency (GHz)")
    figure.suptitle("Free-form renderer repair: pre-repair flat curve vs released r12")
    figure.tight_layout()
    figure.savefig(output / "before-after-s11.png", dpi=180)
    plt.close(figure)


def _report(summary: Day65RepairAnalysisSummary) -> str:
    lines = [
        "# Day 6.5 free-form renderer repair and frozen-candidate re-verdict",
        "",
        f"Final dual-band status: `{summary.final_dual_band_verdict}`.",
        "The Day 6 oracle evidence is retained; only the broken free-form openEMS "
        "renderer and its downstream cross-solver interpretation are superseded.",
        "",
        "## Rotation-invariance release gate",
        "",
        "| solver | orientation | f_res | S11 | source |",
        "|---|---|---:|---:|---|",
    ]
    for item in summary.rotation.orientations:
        for solver, resonance in (
            ("NEC2", item.nec2_resonance),
            ("openEMS", item.openems_resonance),
        ):
            lines.append(
                f"| {solver} | {item.orientation} | "
                f"{resonance.frequency_hz / 1e9:.3f} GHz | "
                f"{resonance.s11_db:.6f} dB | `{summary.rotation_source_run_id}` |"
            )
    lines.extend([
        "",
        "All pairwise decisions:",
        "",
        "| solver | pair | delta f | delta depth | Pearson | pass |",
        "|---|---|---:|---:|---:|---|",
    ])
    for comparison in summary.rotation.comparisons:
        lines.append(
            f"| {comparison.solver} | {comparison.first}/{comparison.second} | "
            f"{comparison.frequency_relative_difference:.6%} | "
            f"{comparison.s11_depth_difference_db:.6f} dB | "
            f"{comparison.pearson:.9f} | {comparison.passed} |"
        )
    lines.extend([
        "",
        "Both solver controls pass. The repaired openEMS instrument is released only "
        "at r12's 6x/240k setting.",
        "",
        "## Candidate A high-band self-convergence diagnostic",
        "",
        "| mesh | f_min | S11 | valid | elapsed | shift | source |",
        "|---:|---:|---:|---|---:|---:|---|",
    ])
    for row in summary.convergence:
        lines.append(
            f"| {row.refinement:g}x | {row.high_band.minimum_frequency_hz / 1e9:.3f} GHz | "
            f"{row.high_band.minimum_s11_db:.6f} dB | {row.high_band.valid} | "
            f"{row.simulation_time_seconds:.3f} s | {row.shift_from_previous} | "
            f"`{row.source_run_id}` |"
        )
    lines.extend([
        "",
        f"Diagnostic verdict: `{summary.convergence_verdict}`. Missing valid -6 dB "
        "resonances are never interpreted as zero movement.",
        "",
        "## Frozen candidate re-verdict",
        "",
        "| candidate | band | NEC2 f/S11 | openEMS f/S11 | gap | verdict | source |",
        "|---|---|---|---|---:|---|---|",
    ])
    for candidate_summary in summary.candidates:
        for band_name, band, verdict in (
            ("2.4 GHz", candidate_summary.decision.low_band, candidate_summary.low_band_verdict),
            ("5.8 GHz", candidate_summary.decision.high_band, candidate_summary.high_band_verdict),
        ):
            lines.append(
                f"| {'A' if candidate_summary.selected_design.rank == 1 else 'B'} | {band_name} | "
                f"{band.nec2.minimum_frequency_hz / 1e9:.3f} GHz / "
                f"{band.nec2.minimum_s11_db:.6f} dB | "
                f"{band.openems.minimum_frequency_hz / 1e9:.3f} GHz / "
                f"{band.openems.minimum_s11_db:.6f} dB | "
                f"{band.resonance_relative_difference} | `{verdict}` | `{candidate_summary.run_id}` |"
            )
        lines.append(
            f"| {'A' if candidate_summary.selected_design.rank == 1 else 'B'} | whole sweep | "
            f"lambda/160 | openEMS 6x | -- | Pearson "
            f"{candidate_summary.whole_sweep_pearson:.9f}; dual `{candidate_summary.dual_band_verdict}` | "
            f"`{candidate_summary.run_id}` |"
        )
    lines.extend([
        "",
        "No frozen candidate is relabeled a dual-band discovery unless both bands "
        "and the whole-sweep correlation pass the unchanged gates. The pre-repair "
        "flat curves remain visible in the overlay as evidence of the detected "
        "instrument failure.",
        "",
        "![Renderer repair before/after curves](before-after-s11.png)",
        "",
    ])
    return "\n".join(lines)


def write_day65_repair_analysis(repo_root: Path) -> Day65RepairAnalysisSummary:
    """Write LF-only JSON/Markdown plus the source-backed repair overlay."""

    summary = build_day65_repair_analysis(repo_root)
    output = repo_root / REPAIR_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "summary.json", summary.model_dump(mode="json"))
    (output / "report.md").write_bytes((_report(summary) + "\n").encode("utf-8"))
    _plot_before_after(repo_root, output, summary.candidates)
    return summary
