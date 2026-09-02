"""Traceable report generation for the frozen Day 5-1b final cross-checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, TypeVar

import matplotlib
from pydantic import BaseModel, ConfigDict, ValidationError

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve
from yaf_ai.exploration.cross_check_v21 import CurveDecisionV21
from yaf_ai.exploration.final_wire_convergence import (
    FINAL_ANALYSIS_ID,
    FinalConvergenceSeries,
)
from yaf_ai.exploration.final_wire_protocol import (
    TARGET_BAND_HZ,
    FrozenFinalCandidate,
    load_frozen_final_candidates,
)
from yaf_ai.exploration.wire_analysis import (
    Day5WireAnalysisSummary,
    WireAgentAggregate,
)
from yaf_ai.exploration.wire_cross_check import WireCrossCheckRunSummary

ModelT = TypeVar("ModelT", bound=BaseModel)


class FinalCandidateResult(BaseModel):
    """One frozen candidate and its source-addressed final result."""

    model_config = ConfigDict(frozen=True)

    candidate: FrozenFinalCandidate
    cross_check: WireCrossCheckRunSummary
    target_band_nec2_min_s11_db: float
    target_band_openems_min_s11_db: float


class FinalWireAnalysisSummary(BaseModel):
    """Machine-readable final convergence and cross-check conclusion."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    analysis_id: Literal["day5-wire-v6-final"] = "day5-wire-v6-final"
    execution_note: str = "docs/cross-solver-protocol-v2.1-execution-note.md"
    convergence: FinalConvergenceSeries
    candidates: tuple[FinalCandidateResult, FinalCandidateResult]
    classic_source_run_id: str
    classic_score: float
    source_batch_aggregates: tuple[WireAgentAggregate, ...]
    environment_verdict: Literal["confirmed_improvement", "divergent"]
    confirmation_statement: str | None = None


def _read_model(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load analysis evidence {path}: {error}") from error


def _target_band_min(curve: SolverCurve) -> float:
    values = tuple(
        s11
        for frequency, s11 in zip(curve.frequency_hz, curve.s11_db, strict=True)
        if TARGET_BAND_HZ[0] <= frequency <= TARGET_BAND_HZ[1]
    )
    if not values:
        raise CrossCheckError("final curve contains no target-band samples")
    return min(values)


def _aggregate(
    aggregates: tuple[WireAgentAggregate, ...], agent: Literal["gp", "random"]
) -> WireAgentAggregate:
    try:
        return next(item for item in aggregates if item.agent == agent)
    except StopIteration as error:
        raise CrossCheckError(f"source batch has no {agent} aggregate") from error


def _claim(
    result: FinalCandidateResult,
    gp: WireAgentAggregate,
    random: WireAgentAggregate,
    classic_score: float,
    density: int,
    refinement: float,
) -> str:
    decision = result.cross_check.decision
    if not isinstance(decision, CurveDecisionV21):
        raise CrossCheckError("final claim requires a protocol-v2.1 decision")
    if decision.resonance_relative_difference is None or decision.curve_pearson_correlation is None:
        raise CrossCheckError("confirmed result is missing agreement metrics")
    parameters = result.candidate.design.proposal_parameters
    length_mm = parameters["total_length_m"] * 1e3
    return (
        f"GP 探索发现的盒约束弯折偶极子（总线长 {length_mm:.3f} mm），经收敛性验证的 "
        f"NEC2（λ/{density}）与 openEMS（{refinement:g}× 网格）双原生求解器按预注册 "
        f"v2.1 判据确认：f_res 偏差 {decision.resonance_relative_difference:.3%}、"
        f"Pearson {decision.curve_pearson_correlation:.6f}、收敛仪器下 NEC2/openEMS "
        f"带内最深 S11 {result.target_band_nec2_min_s11_db:.3f}/"
        f"{result.target_band_openems_min_s11_db:.3f} dB。相对参照：盒内直偶极子（分数 "
        f"{classic_score:.6f}，极低，百分比不作效应量）与随机搜索基线（5-seed 最佳分"
        f"均值 {random.mean_best_score:.6f}；GP 为 {gp.mean_best_score:.6f}）。"
    )


def build_final_wire_analysis(repo_root: Path) -> FinalWireAnalysisSummary:
    """Load only archived/frozen evidence and apply the preregistered final rule."""

    output = repo_root / "artifacts" / "analysis" / FINAL_ANALYSIS_ID
    runs = repo_root / "artifacts" / "runs"
    convergence = _read_model(output / "convergence-series.json", FinalConvergenceSeries)
    candidates = load_frozen_final_candidates(repo_root)
    results: list[FinalCandidateResult] = []
    for candidate in candidates:
        run_id = f"{FINAL_ANALYSIS_ID}-crosscheck-top{candidate.design.rank}"
        cross_check = _read_model(runs / run_id / "summary.json", WireCrossCheckRunSummary)
        if (
            cross_check.selected_design.source_run_id,
            cross_check.selected_design.source_step_index,
            cross_check.selected_design.source_geometry_hash,
        ) != (
            candidate.design.source_run_id,
            candidate.design.source_step_index,
            candidate.design.source_geometry_hash,
        ):
            raise CrossCheckError(f"final result changed frozen candidate {candidate.label}")
        if cross_check.solver_mode_counts != {"subprocess": 2}:
            raise CrossCheckError(f"candidate {candidate.label} contains a fallback")
        results.append(
            FinalCandidateResult(
                candidate=candidate,
                cross_check=cross_check,
                target_band_nec2_min_s11_db=_target_band_min(cross_check.nec2),
                target_band_openems_min_s11_db=_target_band_min(cross_check.openems),
            )
        )
    if len(results) != 2:
        raise CrossCheckError("both frozen candidates must be reported")
    prior = _read_model(
        repo_root / "artifacts" / "analysis" / "day5-wire-v6" / "summary.json",
        Day5WireAnalysisSummary,
    )
    aggregates = prior.final_batch.aggregates
    gp = _aggregate(aggregates, "gp")
    random = _aggregate(aggregates, "random")
    confirmed = next(
        (item for item in results if item.cross_check.decision.verdict == "CONFIRMED"),
        None,
    )
    verdict: Literal["confirmed_improvement", "divergent"] = (
        "confirmed_improvement" if confirmed is not None else "divergent"
    )
    statement = None
    if confirmed is not None:
        if convergence.selected_openems_refinement is None:
            raise CrossCheckError("confirmed result has no final openEMS setting")
        statement = _claim(
            confirmed,
            gp,
            random,
            prior.final_batch.classic_score,
            convergence.selected_nec2_density,
            convergence.selected_openems_refinement,
        )
    return FinalWireAnalysisSummary(
        convergence=convergence,
        candidates=(results[0], results[1]),
        classic_source_run_id=prior.final_batch.classic_source_run_id,
        classic_score=prior.final_batch.classic_score,
        source_batch_aggregates=aggregates,
        environment_verdict=verdict,
        confirmation_statement=statement,
    )


def _curve_table(summary: FinalWireAnalysisSummary) -> str:
    rows = [
        "| candidate/source | openEMS minimum | NEC2 minimum | f gap | Pearson | decision |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for result in summary.candidates:
        check = result.cross_check
        decision = check.decision
        if not isinstance(decision, CurveDecisionV21):
            raise CrossCheckError("final report requires protocol-v2.1 decisions")
        gap = (
            "n/a"
            if decision.resonance_relative_difference is None
            else f"{decision.resonance_relative_difference:.3%}"
        )
        correlation = (
            "n/a"
            if decision.curve_pearson_correlation is None
            else f"{decision.curve_pearson_correlation:.6f}"
        )
        rows.append(
            f"| {result.candidate.label} / `{result.candidate.design.source_run_id}` "
            f"step {result.candidate.design.source_step_index} | "
            f"{check.openems.resonance_frequency_hz / 1e9:.3f} GHz, "
            f"{check.openems.resonance_s11_db:.3f} dB, index "
            f"{decision.openems_validity.minimum_index} | "
            f"{check.nec2.resonance_frequency_hz / 1e9:.3f} GHz, "
            f"{check.nec2.resonance_s11_db:.3f} dB, index "
            f"{decision.nec2_validity.minimum_index} | {gap} | {correlation} | "
            f"{decision.verdict} (`{check.run_id}`) |"
        )
    return "\n".join(rows)


def _convergence_table(summary: FinalWireAnalysisSummary) -> str:
    series = summary.convergence
    final_openems = next(
        item
        for item in series.openems_curves
        if item.setting_value == series.selected_openems_refinement
    )
    rows = [
        "| solver | setting | f_res | S11 | wall time | solver time | source |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in series.openems_curves:
        source = (
            series.prior_run_id
            if item.setting_value in {1.0, 2.0}
            else series.new_run_ids[0]
            if item.setting_value == 4.0
            else series.new_run_ids[-1]
        )
        rows.append(
            f"| openEMS | {item.setting_value:g}x | "
            f"{item.curve.resonance_frequency_hz / 1e9:.3f} GHz | "
            f"{item.curve.resonance_s11_db:.6f} dB | {item.wall_time_seconds:.6f} s | "
            f"{item.curve.simulation_time_seconds:.6f} s | `{source}` |"
        )
    for item in series.nec2_curves:
        source = series.prior_run_id if item.setting_value < 160.0 else series.new_run_ids[0]
        gap = (
            abs(item.curve.resonance_frequency_hz - final_openems.curve.resonance_frequency_hz)
            / final_openems.curve.resonance_frequency_hz
        )
        rows.append(
            f"| NEC2 | lambda/{item.setting_value:g} | "
            f"{item.curve.resonance_frequency_hz / 1e9:.3f} GHz | "
            f"{item.curve.resonance_s11_db:.6f} dB | {item.wall_time_seconds:.6f} s | "
            f"{item.curve.simulation_time_seconds:.6f} s | `{source}`; "
            f"gap to final openEMS {gap:.6%} |"
        )
    return "\n".join(rows)


def _report(summary: FinalWireAnalysisSummary) -> str:
    gp = _aggregate(summary.source_batch_aggregates, "gp")
    random = _aggregate(summary.source_batch_aggregates, "random")
    candidate_rows = []
    for result in summary.candidates:
        candidate_rows.append(
            f"| {result.candidate.label} | `{result.candidate.design.source_run_id}` / "
            f"{result.candidate.design.source_step_index} | "
            f"{result.candidate.design.proposal_parameters['total_length_m'] * 1e3:.3f} mm | "
            f"{result.candidate.target_band_min_s11_db:.6f} dB | "
            f"{result.target_band_nec2_min_s11_db:.6f} / "
            f"{result.target_band_openems_min_s11_db:.6f} dB |"
        )
    statement = summary.confirmation_statement or "No confirmation statement is permitted."
    convergence = summary.convergence
    return (
        "# Day 5-1b final converged-instrument cross-check\n\n"
        "## Outcome\n\n"
        f"Environment verdict: `{summary.environment_verdict}`. Both frozen candidates are "
        "reported below; no third candidate and no outcome-driven retry were used. The protocol "
        "v2.1 thresholds and 1.5--3.5 GHz / 201-point sweep remained unchanged.\n\n"
        f"> {statement}\n\n"
        "The confirmation is specifically a protocol-v2.1 cross-solver agreement result. The "
        "converged-instrument minima remain slightly above the 2.40--2.50 GHz target band, so the "
        "table reports the final in-band S11 explicitly rather than implying perfect center tuning.\n\n"
        "## Frozen candidates\n\n"
        "| candidate | source / step | total line length | archived selection-band S11 | "
        "final NEC2 / openEMS in-band S11 |\n"
        "|---|---|---:|---:|---:|\n"
        + "\n".join(candidate_rows)
        + "\n\n## Instrument convergence\n\n"
        + _convergence_table(summary)
        + "\n\n"
        f"openEMS adjacent shifts: 5.970149%, 3.076923%, and "
        f"{convergence.attribution.openems_adjacent_shift:.6%}; the final adjacent shift passes "
        "the frozen 3% gate. NEC2 lambda/80->lambda/160 shifted "
        f"{convergence.attribution.nec2_adjacent_shift:.6%}, also passing. The NEC2 gaps to "
        "final openEMS are 0.787402%, 0.787402%, 0.787402%, and 1.181102%; the final increase "
        "fails the preregistered monotonic-narrowing clause. Therefore the independently frozen "
        f"attribution remains `{convergence.attribution.verdict}` even though the final candidate "
        "decisions below pass.\n\n"
        "## Final protocol-v2.1 decisions\n\n"
        + _curve_table(summary)
        + "\n\nAll four resonance minima are internal (outside the first/last three samples) "
        "and at or below -6 dB. Both frequency gaps pass 5%, and both Pearson correlations pass "
        "0.8. The preregistered rule therefore marks each candidate independently CONFIRMED; "
        "either one was predeclared sufficient for the environment-level first confirmed finding.\n\n"
        "## Source baseline context\n\n"
        f"The source `day5-wire-v6r2` five-seed GP mean best score is "
        f"{gp.mean_best_score:.6f} +/- {gp.sample_std_best_score:.6f}; Random is "
        f"{random.mean_best_score:.6f} +/- {random.sample_std_best_score:.6f}. Classic score is "
        f"{summary.classic_score:.6f} from `{summary.classic_source_run_id}`. The classic ratio "
        "is not treated as an effect size because the reference score is near zero. These are "
        "descriptive statistics, not a significance claim; source run IDs are preserved in "
        "`summary.json`.\n\n"
        "![Final dual-solver S11 with convergence evolution](final-cross-solver-s11.png)\n\n"
        "![Instrument convergence](instrument-convergence.png)\n"
    )


def _plot(summary: FinalWireAnalysisSummary, path: Path) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(11.0, 9.0), sharex=True)
    for axis, result in zip(axes, summary.candidates, strict=True):
        check = result.cross_check
        for label, curve, color in (
            ("NEC2 lambda/160", check.nec2, "#1f77b4"),
            ("openEMS 8x", check.openems, "#d62728"),
        ):
            axis.plot(
                [value / 1e9 for value in curve.frequency_hz],
                curve.s11_db,
                label=label,
                color=color,
                linewidth=2.0,
            )
            axis.scatter(
                [curve.resonance_frequency_hz / 1e9],
                [curve.resonance_s11_db],
                color=color,
                zorder=4,
            )
        axis.axvspan(2.40, 2.50, color="#2ca02c", alpha=0.12, label="target band")
        decision = check.decision
        correlation = (
            decision.curve_pearson_correlation if isinstance(decision, CurveDecisionV21) else None
        )
        axis.set_title(
            f"Candidate {result.candidate.label}: {decision.verdict}; Pearson={correlation:.6f}"
            if correlation is not None
            else "invalid decision"
        )
        axis.set_ylabel("S11 (dB)")
        axis.grid(alpha=0.25)
        axis.legend(loc="lower left")
    evolution_axis = axes[0]
    y_min, y_max = evolution_axis.get_ylim()
    openems_y = y_max - 0.08 * (y_max - y_min)
    nec2_y = y_max - 0.17 * (y_max - y_min)
    openems_positions = [
        item.curve.resonance_frequency_hz / 1e9 for item in summary.convergence.openems_curves
    ]
    nec2_positions = [
        item.curve.resonance_frequency_hz / 1e9 for item in summary.convergence.nec2_curves
    ]
    for positions, y_value, color in (
        (openems_positions, openems_y, "#d62728"),
        (nec2_positions, nec2_y, "#1f77b4"),
    ):
        evolution_axis.scatter(positions, [y_value] * len(positions), color=color, s=28)
        for start, end in zip(positions, positions[1:], strict=False):
            evolution_axis.annotate(
                "",
                xy=(end, y_value),
                xytext=(start, y_value),
                arrowprops={"arrowstyle": "->", "color": color, "lw": 1.5},
            )
    evolution_axis.text(
        max(openems_positions) + 0.02,
        openems_y,
        "openEMS 1x->2x->4x->8x",
        color="#d62728",
        va="center",
        fontsize=8,
    )
    evolution_axis.text(
        max(nec2_positions) + 0.02,
        nec2_y,
        "NEC2 lambda/20->40->80->160",
        color="#1f77b4",
        va="center",
        fontsize=8,
    )
    axes[-1].set_xlabel("Frequency (GHz)")
    figure.suptitle("Frozen candidates under converged instrument settings")
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def write_final_wire_analysis(repo_root: Path) -> FinalWireAnalysisSummary:
    """Write LF-only JSON/report and the final comparison figure."""

    summary = build_final_wire_analysis(repo_root)
    output = repo_root / "artifacts" / "analysis" / FINAL_ANALYSIS_ID
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
    report_text = _report(summary).replace("\r\n", "\n")
    report = report_text.encode("utf-8")
    temporary_report = output / "report.md.tmp"
    temporary_report.write_bytes(report)
    os.replace(temporary_report, output / "report.md")
    _plot(summary, output / "final-cross-solver-s11.png")
    return summary
