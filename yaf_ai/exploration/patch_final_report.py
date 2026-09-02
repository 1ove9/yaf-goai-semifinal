"""Final scoped resolution of the Day 2 wifi24 patch result."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

import matplotlib
from pydantic import BaseModel, ConfigDict, ValidationError

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from yaf_ai.exploration.analysis import (
    AgentAggregate,
    BatchAnalysisSummary,
    ClassicComparison,
    DiscoveryDecision,
)
from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.cross_check_v2 import ConvergenceRunSummary
from yaf_ai.exploration.patch_final_analysis import build_patch_convergence_series
from yaf_ai.exploration.patch_final_convergence import PatchConvergenceSeries
from yaf_ai.exploration.patch_final_cross_check import (
    PatchFinalCrossCheckSummary,
    load_patch_final_cross_check,
)
from yaf_ai.exploration.patch_final_protocol import SOURCE_CONVERGENCE_RUN_ID


class PatchFinalResolutionSummary(BaseModel):
    """Machine-readable final result without mutating historical artifacts."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    analysis_id: Literal["day5-patch-final"] = "day5-patch-final"
    convergence: PatchConvergenceSeries
    cross_check: PatchFinalCrossCheckSummary
    day2_wifi24_gp: AgentAggregate
    day2_wifi24_random: AgentAggregate
    day2_wifi24_classic_comparison: ClassicComparison
    day2_original_decision: DiscoveryDecision
    day2_resolved_verdict: Literal[
        "confirmed_improvement", "insufficient_evidence"
    ]
    attribution: Literal["instrument_boundary"] = "instrument_boundary"
    scope_statement: str
    upgrade_statement: str | None = None


def _load_day2(repo_root: Path) -> BatchAnalysisSummary:
    path = repo_root / "artifacts" / "analysis" / "day2" / "summary.json"
    try:
        return BatchAnalysisSummary.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load Day 2 analysis: {error}") from error


def build_patch_final_resolution(repo_root: Path) -> PatchFinalResolutionSummary:
    """Apply the preregistered scope rule to the one archived v2.1 decision."""

    convergence = build_patch_convergence_series(repo_root)
    cross_check = load_patch_final_cross_check(repo_root)
    day2 = _load_day2(repo_root)
    try:
        gp = next(
            item
            for item in day2.aggregates
            if item.spec == "wifi24" and item.agent == "gp"
        )
        random = next(
            item
            for item in day2.aggregates
            if item.spec == "wifi24" and item.agent == "random"
        )
        classic = next(
            item
            for item in day2.classic_comparisons
            if item.spec == "wifi24" and item.agent == "gp"
        )
        original = next(
            item for item in day2.discovery_decisions if item.spec == "wifi24"
        )
    except StopIteration as error:
        raise CrossCheckError("Day 2 analysis lacks a unique wifi24 row") from error
    confirmed = cross_check.decision.verdict == "CONFIRMED"
    resolved: Literal["confirmed_improvement", "insufficient_evidence"] = (
        "confirmed_improvement" if confirmed else "insufficient_evidence"
    )
    scope = (
        "Performance values for the original FR4 design remain openEMS results; "
        "the cross-check tests the credibility of openEMS for this geometry class."
    )
    upgrade = None
    if confirmed:
        upgrade = (
            "Day 2 wifi24 is upgraded to confirmed_improvement: the GP mean exceeds "
            f"classic by {classic.improvement_fraction:.2%}, and the frozen air-variant "
            "solver chain passes protocol v2.1. "
            + scope
        )
    return PatchFinalResolutionSummary(
        convergence=convergence,
        cross_check=cross_check,
        day2_wifi24_gp=gp,
        day2_wifi24_random=random,
        day2_wifi24_classic_comparison=classic,
        day2_original_decision=original,
        day2_resolved_verdict=resolved,
        scope_statement=scope,
        upgrade_statement=upgrade,
    )


def _load_prior(repo_root: Path) -> ConvergenceRunSummary:
    path = (
        repo_root
        / "artifacts"
        / "runs"
        / SOURCE_CONVERGENCE_RUN_ID
        / "summary.json"
    )
    try:
        return ConvergenceRunSummary.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load prior patch convergence: {error}") from error


def _report(summary: PatchFinalResolutionSummary) -> str:
    decision = summary.cross_check.decision
    final_grid = summary.convergence.nec2_runs[-1]
    gap_text = (
        "n/a"
        if decision.resonance_relative_difference is None
        else f"{decision.resonance_relative_difference:.6%}"
    )
    pearson_text = (
        "n/a"
        if decision.curve_pearson_correlation is None
        else f"{decision.curve_pearson_correlation:.9f}"
    )
    depth_text = (
        "n/a"
        if decision.s11_depth_difference_db is None
        else f"{decision.s11_depth_difference_db:.6f} dB"
    )
    upgrade = (
        f"> {summary.upgrade_statement}\n\n"
        if summary.upgrade_statement is not None
        else (
            "No Day 2 upgrade statement is permitted: the unique final comparison is "
            "DIVERGENT. Wifi24 remains `insufficient_evidence`.\n\n"
        )
    )
    return (
        "# Day 5-2 final patch cross-check\n\n"
        "## Outcome\n\n"
        f"Final protocol-v2.1 verdict: `{decision.verdict}`. Day 2 wifi24 resolved "
        f"verdict: `{summary.day2_resolved_verdict}`. The unique candidate and the "
        "pre-registered 4.098041023--6.830068372 GHz / 51-point sweep were not changed; "
        "no grid beyond 44 and no retry were used.\n\n"
        + upgrade
        + "## Complete decision\n\n"
        "| solver | source | minimum | index / samples | interior | depth <= -6 dB |\n"
        "|---|---|---:|---:|---|---|\n"
        f"| openEMS 2x | `{summary.cross_check.openems_source_run_id}` | "
        f"{summary.cross_check.openems.resonance_frequency_hz / 1e9:.6f} GHz / "
        f"{summary.cross_check.openems.resonance_s11_db:.6f} dB | "
        f"{decision.openems_validity.minimum_index} / "
        f"{decision.openems_validity.sample_count} | "
        f"{decision.openems_validity.interior_minimum} | "
        f"{decision.openems_validity.depth_threshold_met} |\n"
        f"| NEC2 grid 44 | `{summary.cross_check.nec2_source_run_id}` | "
        f"{summary.cross_check.nec2.resonance_frequency_hz / 1e9:.6f} GHz / "
        f"{summary.cross_check.nec2.resonance_s11_db:.6f} dB | "
        f"{decision.nec2_validity.minimum_index} / "
        f"{decision.nec2_validity.sample_count} | "
        f"{decision.nec2_validity.interior_minimum} | "
        f"{decision.nec2_validity.depth_threshold_met} |\n\n"
        f"Resonance difference is {gap_text} (threshold <=5%, met: "
        f"{decision.resonance_threshold_met}); Pearson is {pearson_text} (threshold >=0.8, "
        f"met: {decision.curve_correlation_threshold_met}). S11-depth difference is "
        f"{depth_text} and remains record-only.\n\n"
        "## Attribution and compute roadmap\n\n"
        "The fixed-reference grid gap narrows monotonically from 31.111425% at grid 6 "
        "to 5.554467% at grid 44. This retains the Day 4 `instrument_boundary` "
        "attribution, but the completed ladder has not crossed the final agreement gates. "
        f"The all-point power-law roadmap estimates grid "
        f"{final_grid.extrapolation.estimated_grid_for_five_percent} for 5%; the frozen "
        f"wire-reference Pearson mapping estimates grid "
        f"{final_grid.extrapolation.estimated_grid_for_pearson}. The latter is descriptive "
        "and potentially optimistic: the measured patch Pearson at grid 44 is only "
        f"{pearson_text}, showing that cross-geometry gap-to-correlation transfer is weak. "
        "Neither estimate authorizes an unregistered extra run.\n\n"
        "## Day 2 context and scope\n\n"
        f"The archived five-seed wifi24 GP mean is "
        f"{summary.day2_wifi24_gp.mean_best_score:.6f} +/- "
        f"{summary.day2_wifi24_gp.sample_std_best_score:.6f}; Random is "
        f"{summary.day2_wifi24_random.mean_best_score:.6f} +/- "
        f"{summary.day2_wifi24_random.sample_std_best_score:.6f}. GP remains "
        f"{summary.day2_wifi24_classic_comparison.improvement_fraction:.2%} above classic, "
        "but its sole cross-solver gap is unresolved. Wifi58 and n78 remain "
        "`inconclusive_needs_spec_specific_grid_study`. Existing Day 2/3/4 artifacts are "
        "not modified.\n\n"
        f"Pre-registered scope text (not activated as a confirmation claim): "
        f'"{summary.scope_statement}"\n\n'
        "Full timing and fixed-reference method comparison are in `convergence.md`.\n\n"
        "![Final patch S11 and grid resonance migration](final-patch-s11.png)\n\n"
        "![Patch and wire fixed-reference convergence](convergence-comparison.png)\n"
    )


def _plot(
    output: Path,
    summary: PatchFinalResolutionSummary,
    prior: ConvergenceRunSummary,
) -> None:
    check = summary.cross_check
    gap = check.decision.resonance_relative_difference
    pearson = check.decision.curve_pearson_correlation
    if gap is None or pearson is None:
        raise CrossCheckError("final patch decision lacks gap or Pearson evidence")
    figure, axis = plt.subplots(figsize=(11.2, 6.3))
    axis.plot(
        [value / 1e9 for value in check.openems.frequency_hz],
        check.openems.s11_db,
        color="#d62728",
        linewidth=2.2,
        label="openEMS 2x",
    )
    axis.plot(
        [value / 1e9 for value in check.nec2.frequency_hz],
        check.nec2.s11_db,
        color="#1f77b4",
        linewidth=2.2,
        label="NEC2 grid 44",
    )
    axis.scatter(
        [check.openems.resonance_frequency_hz / 1e9],
        [check.openems.resonance_s11_db],
        color="#d62728",
        zorder=4,
    )
    axis.scatter(
        [check.nec2.resonance_frequency_hz / 1e9],
        [check.nec2.resonance_s11_db],
        color="#1f77b4",
        zorder=4,
    )
    points = (*prior.points, *(item.point for item in summary.convergence.nec2_runs))
    positions = [item.nec2_resonance_frequency_hz / 1e9 for item in points]
    grids = [item.grid_intervals for item in points]
    y_min, y_max = axis.get_ylim()
    arrow_y = y_max - 0.1 * (y_max - y_min)
    axis.scatter(positions, [arrow_y] * len(positions), color="#7b2cbf", s=34)
    for start, stop in zip(positions, positions[1:], strict=False):
        axis.annotate(
            "",
            xy=(stop, arrow_y),
            xytext=(start, arrow_y),
            arrowprops={"arrowstyle": "->", "color": "#7b2cbf", "lw": 1.5},
        )
    label_offsets = ((0, 7), (0, 7), (0, 7), (-11, 18), (-11, -3), (14, 10))
    for position, grid, offset in zip(
        positions, grids, label_offsets, strict=True
    ):
        axis.annotate(
            f"g{grid}",
            xy=(position, arrow_y),
            xytext=offset,
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )
    axis.axvline(
        check.openems.resonance_frequency_hz / 1e9,
        color="#d62728",
        linestyle=":",
        alpha=0.7,
    )
    axis.set_title(
        "Final patch air-variant cross-check: "
        f"{check.decision.verdict}, gap={gap:.3%}, Pearson={pearson:.6f}"
    )
    axis.set_xlabel("Frequency (GHz)")
    axis.set_ylabel("S11 (dB)")
    axis.grid(alpha=0.25)
    axis.legend(loc="lower right")
    figure.tight_layout()
    figure.savefig(output / "final-patch-s11.png", dpi=180)
    plt.close(figure)


def write_patch_final_report(repo_root: Path) -> PatchFinalResolutionSummary:
    """Write final LF-only JSON/report and the preregistered main figure."""

    summary = build_patch_final_resolution(repo_root)
    prior = _load_prior(repo_root)
    output = repo_root / "artifacts" / "analysis" / "day5-patch-final"
    output.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            summary.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    temporary = output / "summary.json.tmp"
    temporary.write_bytes(payload)
    os.replace(temporary, output / "summary.json")
    report = _report(summary).encode("utf-8")
    temporary_report = output / "report.md.tmp"
    temporary_report.write_bytes(report)
    os.replace(temporary_report, output / "report.md")
    _plot(output, summary, prior)
    return summary
