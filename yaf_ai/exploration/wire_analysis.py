"""Source-addressed descriptive analysis for the Day 4 wire experiment."""

from __future__ import annotations

import json
import os
import statistics
import tempfile
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "yaf-matplotlib")
)

import matplotlib
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.baselines import _proposal_from_parameters
from yaf_ai.exploration.batch import (
    BatchConfigDocument,
    BatchRunRecord,
    BatchState,
    load_batch_config,
    load_batch_state,
)
from yaf_ai.exploration.cross_check_v21 import CurveDecisionV21
from yaf_ai.exploration.day5_wire_convergence import Day5ConvergenceSummary
from yaf_ai.exploration.environment import ExplorationConfig
from yaf_ai.exploration.logger import AuditStepRecord, RunSummary
from yaf_ai.exploration.wire_cross_check import WireCrossCheckRunSummary

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


class WireAnalysisError(RuntimeError):
    """Raised when a source-addressed wire result is incomplete or inconsistent."""


class WireRunRow(BaseModel):
    """One traceable matrix cell with its complete best-so-far sequence."""

    model_config = ConfigDict(frozen=True)

    agent: str
    seed: int
    source_run_id: str
    config_hash: str
    best_score: float
    best_min_s11_db: float
    best_gain_dbi: float
    best_realized_gain_dbi: float
    best_vswr: float
    evaluations_to_best: int = Field(gt=0)
    best_so_far: tuple[float, ...]
    best_geometry_hash: str
    best_parameters: dict[str, float]
    solver_modes: tuple[str, ...]


class WireAgentAggregate(BaseModel):
    """Descriptive best-score statistics over matched seeds."""

    model_config = ConfigDict(frozen=True)

    agent: Literal["gp", "random"]
    count: int = Field(gt=0)
    mean_best_score: float
    sample_std_best_score: float
    relative_to_classic: float
    source_run_ids: tuple[str, ...]


class WirePairedDifference(BaseModel):
    """One matched-seed GP-minus-random comparison."""

    model_config = ConfigDict(frozen=True)

    seed: int
    gp_score: float
    random_score: float
    difference: float
    gp_source_run_id: str
    random_source_run_id: str


class WireAnalysisSummary(BaseModel):
    """Machine-readable Day 4 analysis with native cross-check evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str
    batch_config_hash: str
    batch_config: dict[str, Any]
    rows: tuple[WireRunRow, ...]
    classic_source_run_id: str
    classic_score: float
    aggregates: tuple[WireAgentAggregate, ...]
    paired_differences: tuple[WirePairedDifference, ...]
    cross_checks: tuple[WireCrossCheckRunSummary, ...]
    verdict: Literal[
        "confirmed_improvement",
        "divergent",
        "insufficient_evidence",
    ]
    confirmed_source_run_id: str | None = None
    confirmed_improvement_fraction: float | None = None


class Day5WireAnalysisSummary(BaseModel):
    """Final Day 5 matrix, prior-batch comparison, and attribution evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    output_id: str = "day5-wire-v6"
    final_batch: WireAnalysisSummary
    v5_aggregates: tuple[WireAgentAggregate, ...]
    convergence: Day5ConvergenceSummary
    discovery_verdict: Literal["divergent"] = "divergent"
    confirmation_claim_permitted: bool = False


def _write_text_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    os.replace(temporary, path)


def _load_run(artifacts_root: Path, record: BatchRunRecord) -> WireRunRow:
    directory = artifacts_root / record.run_id
    try:
        summary = RunSummary.model_validate_json(
            (directory / "summary.json").read_text(encoding="utf-8")
        )
        evaluations: list[AuditStepRecord] = []
        for line in (directory / "log.jsonl").read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            if raw.get("event_type") == "evaluation":
                evaluations.append(AuditStepRecord.model_validate(raw))
    except (OSError, ValidationError, json.JSONDecodeError) as error:
        raise WireAnalysisError(f"invalid archived run {record.run_id}: {error}") from error
    evaluations.sort(key=lambda item: item.step_index)
    if not evaluations or summary.steps_completed != len(evaluations):
        raise WireAnalysisError(f"incomplete archived run {record.run_id}")
    if {item.solver_mode for item in evaluations} != {"subprocess"}:
        raise WireAnalysisError(f"run {record.run_id} contains non-real solver evidence")
    best_index, best = max(enumerate(evaluations), key=lambda item: item[1].score)
    running = float("-inf")
    best_so_far: list[float] = []
    for item in evaluations:
        running = max(running, item.score)
        best_so_far.append(running)
    return WireRunRow(
        agent=record.agent,
        seed=record.seed,
        source_run_id=record.run_id,
        config_hash=summary.config_hash,
        best_score=best.score,
        best_min_s11_db=best.metrics["min_s11_db"],
        best_gain_dbi=best.metrics["gain_dbi"],
        best_realized_gain_dbi=best.metrics.get(
            "realized_gain_dbi", best.metrics["gain_dbi"]
        ),
        best_vswr=best.metrics["vswr"],
        evaluations_to_best=best_index + 1,
        best_so_far=tuple(best_so_far),
        best_geometry_hash=best.geometry_hash,
        best_parameters=best.proposal_parameters,
        solver_modes=tuple(item.solver_mode for item in evaluations),
    )


def build_wire_analysis(
    state: BatchState,
    document: BatchConfigDocument,
    *,
    artifacts_root: Path,
    cross_checks: tuple[WireCrossCheckRunSummary, ...] = (),
) -> WireAnalysisSummary:
    """Calculate matched descriptive results entirely from archived run evidence."""

    if state.config_hash != document.config_hash:
        raise WireAnalysisError("wire state and config hashes do not match")
    if document.config.experiment_kind != "wire":
        raise WireAnalysisError("batch config is not a wire experiment")
    completed = tuple(record for record in state.runs if record.status == "completed")
    rows = tuple(_load_run(artifacts_root, record) for record in completed)
    classic = next((row for row in rows if row.agent == "classic"), None)
    if classic is None or classic.best_score == 0.0:
        raise WireAnalysisError("wire classic reference is missing or zero")
    aggregates: list[WireAgentAggregate] = []
    for agent in ("gp", "random"):
        group = sorted((row for row in rows if row.agent == agent), key=lambda row: row.seed)
        scores = [row.best_score for row in group]
        if not scores:
            raise WireAnalysisError(f"wire {agent} rows are missing")
        aggregates.append(
            WireAgentAggregate(
                agent=agent,
                count=len(scores),
                mean_best_score=statistics.fmean(scores),
                sample_std_best_score=statistics.stdev(scores) if len(scores) > 1 else 0.0,
                relative_to_classic=statistics.fmean(scores) / classic.best_score - 1.0,
                source_run_ids=tuple(row.source_run_id for row in group),
            )
        )
    gp = {row.seed: row for row in rows if row.agent == "gp"}
    random = {row.seed: row for row in rows if row.agent == "random"}
    paired = tuple(
        WirePairedDifference(
            seed=seed,
            gp_score=gp[seed].best_score,
            random_score=random[seed].best_score,
            difference=gp[seed].best_score - random[seed].best_score,
            gp_source_run_id=gp[seed].source_run_id,
            random_source_run_id=random[seed].source_run_id,
        )
        for seed in sorted(gp.keys() & random.keys())
    )
    confirmed = next(
        (
            item
            for item in sorted(
                cross_checks,
                key=lambda check: check.selected_design.source_score,
                reverse=True,
            )
            if item.decision.verdict == "CONFIRMED"
            and item.selected_design.oracle_improvement_fraction
            >= document.config.discovery_policy.classic_improvement_fraction
        ),
        None,
    )
    if confirmed is not None:
        verdict: Literal[
            "confirmed_improvement", "divergent", "insufficient_evidence"
        ] = "confirmed_improvement"
    elif cross_checks and all(item.decision.verdict == "DIVERGENT" for item in cross_checks):
        verdict = "divergent"
    else:
        verdict = "insufficient_evidence"
    return WireAnalysisSummary(
        batch_id=state.batch_id,
        batch_config_hash=document.config_hash,
        batch_config=document.config.model_dump(mode="json"),
        rows=rows,
        classic_source_run_id=classic.source_run_id,
        classic_score=classic.best_score,
        aggregates=tuple(aggregates),
        paired_differences=paired,
        cross_checks=cross_checks,
        verdict=verdict,
        confirmed_source_run_id=(
            confirmed.selected_design.source_run_id if confirmed is not None else None
        ),
        confirmed_improvement_fraction=(
            confirmed.selected_design.oracle_improvement_fraction
            if confirmed is not None
            else None
        ),
    )


def _load_cross_checks(
    artifacts_root: Path, batch_id: str
) -> tuple[WireCrossCheckRunSummary, ...]:
    results: list[WireCrossCheckRunSummary] = []
    for rank in (1, 2):
        path = artifacts_root / f"{batch_id}-crosscheck-top{rank}" / "summary.json"
        if not path.is_file():
            continue
        try:
            results.append(
                WireCrossCheckRunSummary.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            )
        except (OSError, ValidationError) as error:
            raise WireAnalysisError(f"invalid wire cross-check {path}: {error}") from error
    return tuple(results)


def _plot_best_so_far(summary: WireAnalysisSummary, path: Path) -> None:
    figure, axis = plt.subplots(figsize=(8.2, 4.8))
    for agent, color in (("gp", "#1565c0"), ("random", "#ef6c00")):
        rows = sorted(
            (row for row in summary.rows if row.agent == agent), key=lambda row: row.seed
        )
        for row in rows:
            axis.plot(
                range(1, len(row.best_so_far) + 1),
                row.best_so_far,
                color=color,
                linewidth=0.8,
                alpha=0.28,
            )
        if rows:
            length = min(len(row.best_so_far) for row in rows)
            mean = [
                statistics.fmean(row.best_so_far[index] for row in rows)
                for index in range(length)
            ]
            axis.plot(
                range(1, length + 1), mean, color=color, linewidth=2.5, label=agent
            )
    axis.axhline(summary.classic_score, color="black", linestyle="--", label="classic")
    axis.set_xlabel("NEC2 evaluation number")
    axis.set_ylabel("best composite score so far")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _plot_geometry(
    summary: WireAnalysisSummary, artifacts_root: Path, path: Path
) -> None:
    best = max((row for row in summary.rows if row.agent == "gp"), key=lambda row: row.best_score)
    run_summary = RunSummary.model_validate_json(
        (artifacts_root / best.source_run_id / "summary.json").read_text(encoding="utf-8")
    )
    config = ExplorationConfig.model_validate(run_summary.config)
    geometry = _proposal_from_parameters(config, best.best_parameters, "gp").geometry
    figure, axis = plt.subplots(figsize=(5.4, 5.4))
    for face in geometry.faces:
        first = geometry.vertices[face[0]]
        second = geometry.vertices[face[1]]
        axis.plot(
            [first[0] * 1000.0, second[0] * 1000.0],
            [first[1] * 1000.0, second[1] * 1000.0],
            color="#1565c0",
            linewidth=2.0,
        )
    axis.set_xlim(-15.5, 15.5)
    axis.set_ylim(-15.5, 15.5)
    axis.set_aspect("equal")
    axis.set_xlabel("x (mm)")
    axis.set_ylabel("y (mm)")
    axis.set_title(f"Best GP centerline: {best.source_run_id}")
    axis.grid(alpha=0.2)
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_cross_solver_s11(summary: WireAnalysisSummary, path: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(11.0, 4.5), sharey=True)
    for axis, check in zip(axes, summary.cross_checks, strict=True):
        axis.plot(
            [value / 1e9 for value in check.nec2.frequency_hz],
            check.nec2.s11_db,
            linewidth=2.0,
            label="NEC2 lambda/80",
            color="#1565c0",
        )
        axis.plot(
            [value / 1e9 for value in check.openems.frequency_hz],
            check.openems.s11_db,
            linewidth=2.0,
            label="openEMS 2x",
            color="#ef6c00",
        )
        axis.axhline(-6.0, color="black", linestyle="--", linewidth=1.0)
        axis.set_title(f"top-{check.selected_design.rank}: {check.decision.verdict}")
        axis.set_xlabel("frequency (GHz)")
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("S11 (dB)")
    axes[0].legend()
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _plot_segmentation_convergence(
    convergence: Day5ConvergenceSummary, path: Path
) -> None:
    densities = (20, 40, 80)
    frequencies = [
        curve.resonance_frequency_hz / 1e9 for curve in convergence.nec2_curves
    ]
    figure, axis = plt.subplots(figsize=(7.0, 4.5))
    axis.plot(densities, frequencies, marker="o", linewidth=2.0, label="NEC2")
    axis.axhline(
        convergence.openems_refined.resonance_frequency_hz / 1e9,
        color="#ef6c00",
        linewidth=2.0,
        label="openEMS 2x",
    )
    axis.axhline(
        convergence.openems_default.resonance_frequency_hz / 1e9,
        color="#ef6c00",
        linestyle="--",
        linewidth=1.2,
        label="openEMS 1x",
    )
    axis.set_xlabel("NEC2 segments per wavelength")
    axis.set_ylabel("wideband resonance (GHz)")
    axis.set_xticks(densities)
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def _day5_report(summary: Day5WireAnalysisSummary) -> str:
    final = summary.final_batch
    gp = next(item for item in final.aggregates if item.agent == "gp")
    random = next(item for item in final.aggregates if item.agent == "random")
    v5_gp = next(item for item in summary.v5_aggregates if item.agent == "gp")
    v5_random = next(
        item for item in summary.v5_aggregates if item.agent == "random"
    )
    lines = [
        "# Day 5 wire exploration v6",
        "",
        "## Outcome",
        "",
        (
            "The 50--80 mm v2 attempt was stopped by its preregistered sanity "
            "check and is documented in `ABORTED_V2.md`. The source-addressed "
            "wideband diagnostic justified the separately preregistered 50--100 "
            "mm v2.1 retry `day5-wire-v6r2`."
        ),
        (
            "The retry found valid target-band NEC2 designs and GP beat Random in "
            "all five matched seeds. Both fixed top designs nevertheless failed "
            "the unchanged cross-solver Pearson threshold. Final discovery verdict: "
            "`divergent`; `confirmed_improvement` is not permitted."
        ),
        "",
        "## Matched-seed matrix",
        "",
        "| seed | GP best | Random best | GP-Random | GP source | Random source |",
        "|---:|---:|---:|---:|---|---|",
    ]
    for pair in final.paired_differences:
        lines.append(
            f"| {pair.seed} | {pair.gp_score:.6f} | {pair.random_score:.6f} | "
            f"{pair.difference:+.6f} | `{pair.gp_source_run_id}` | "
            f"`{pair.random_source_run_id}` |"
        )
    lines.extend(
        [
            "",
            "| batch | GP mean +/- SD | Random mean +/- SD | GP/Random |",
            "|---|---:|---:|---:|",
            (
                f"| v5 (budget 40) | {v5_gp.mean_best_score:.6f} +/- "
                f"{v5_gp.sample_std_best_score:.6f} | "
                f"{v5_random.mean_best_score:.6f} +/- "
                f"{v5_random.sample_std_best_score:.6f} | "
                f"{v5_gp.mean_best_score / v5_random.mean_best_score - 1.0:+.2%} |"
            ),
            (
                f"| v6r2 (budget 400) | {gp.mean_best_score:.6f} +/- "
                f"{gp.sample_std_best_score:.6f} | "
                f"{random.mean_best_score:.6f} +/- "
                f"{random.sample_std_best_score:.6f} | "
                f"{gp.mean_best_score / random.mean_best_score - 1.0:+.2%} |"
            ),
            "",
            (
                f"Classic score was {final.classic_score:.6f} from "
                f"`{final.classic_source_run_id}`. Ratios to this near-zero "
                "reference are not treated as effect sizes. The five-seed results "
                "are descriptive; no significance claim is made."
            ),
            "",
            "## Top-1 segmentation and mesh attribution",
            "",
            (
                f"Source: `{summary.convergence.selected_design.source_run_id}` "
                f"step {summary.convergence.selected_design.source_step_index}; "
                f"convergence run `{summary.convergence.run_id}`."
            ),
            "",
            "| model | resolution | f_res | S11 | gap to openEMS 2x | time |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    convergence = summary.convergence
    for density, curve, gap in zip(
        (20, 40, 80),
        convergence.nec2_curves,
        convergence.nec2_to_refined_openems_gaps,
        strict=True,
    ):
        lines.append(
            f"| NEC2 | lambda/{density} | "
            f"{curve.resonance_frequency_hz / 1e9:.3f} GHz | "
            f"{curve.resonance_s11_db:.3f} dB | {gap:.3%} | "
            f"{curve.simulation_time_seconds:.3f} s |"
        )
    lines.extend(
        [
            (
                f"| openEMS | 1x | "
                f"{convergence.openems_default.resonance_frequency_hz / 1e9:.3f} "
                f"GHz | {convergence.openems_default.resonance_s11_db:.3f} dB | "
                "n/a | "
                f"{convergence.openems_default.simulation_time_seconds:.3f} s |"
            ),
            (
                f"| openEMS | 2x | "
                f"{convergence.openems_refined.resonance_frequency_hz / 1e9:.3f} "
                f"GHz | {convergence.openems_refined.resonance_s11_db:.3f} dB | "
                "reference | "
                f"{convergence.openems_refined.simulation_time_seconds:.3f} s |"
            ),
            "",
            (
                f"openEMS shifted {convergence.openems_resonance_relative_shift:.3%} "
                "from 1x to 2x, so its <=3% self-convergence check failed. NEC2 "
                f"gap ratio was {convergence.attribution.finest_to_coarsest_ratio:.3f}; "
                f"the frozen attribution is `{convergence.attribution.verdict}`."
            ),
            "",
            "## Protocol v2.1 top-2 cross-check",
            "",
            "| rank/source | openEMS minimum | NEC2 minimum | f gap | Pearson | decision |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for check in final.cross_checks:
        decision = check.decision
        if not isinstance(decision, CurveDecisionV21):
            raise WireAnalysisError("Day 5 requires protocol v2.1 decisions")
        lines.append(
            f"| {check.selected_design.rank} / "
            f"`{check.selected_design.source_run_id}` step "
            f"{check.selected_design.source_step_index} | "
            f"{decision.openems_validity.minimum_frequency_hz / 1e9:.3f} GHz, "
            f"{decision.openems_validity.minimum_s11_db:.3f} dB, index "
            f"{decision.openems_validity.minimum_index} | "
            f"{decision.nec2_validity.minimum_frequency_hz / 1e9:.3f} GHz, "
            f"{decision.nec2_validity.minimum_s11_db:.3f} dB, index "
            f"{decision.nec2_validity.minimum_index} | "
            f"{decision.resonance_relative_difference:.3%} | "
            f"{decision.curve_pearson_correlation:.6f} | "
            f"{decision.verdict} (`{check.run_id}`) |"
        )
    lines.extend(
        [
            "",
            (
                "Both solvers have valid internal minima deeper than -6 dB, and "
                "both frequency gaps pass 5%. Pearson correlations 0.719342 and "
                "0.718527 fail the preregistered 0.8 threshold, so the result is "
                "DIVERGENT. Coupled with the failed openEMS mesh self-check and "
                "inconclusive segmentation attribution, this is not the first "
                "effective CONFIRMED result."
            ),
            "",
            "![Best-so-far](best-so-far.png)",
            "",
            "![Top GP geometry](best-geometry.png)",
            "",
            "![Dual-solver wideband S11](cross-solver-s11.png)",
            "",
            "![Segmentation convergence](segmentation-convergence.png)",
            "",
        ]
    )
    return "\n".join(lines)


def _report(summary: WireAnalysisSummary) -> str:
    lines = [
        f"# Day 4.5 native wire exploration: {summary.batch_id}",
        "",
        (
            "This replacement analysis follows the retraction in "
            "`artifacts/analysis/day4-wire/RETRACTION.md`; no Day 4 v4 numeric "
            "result is reused as valid performance evidence."
        ),
        "",
        "## Scope",
        "",
        (
            "The scientific question is whether GP can find a planar meander dipole "
            "that outperforms the longest axis-aligned straight dipole in the frozen "
            "30x30 mm box. NEC2 is the exploration oracle; openEMS is an independent "
            "native-centerline verifier under protocol v2.1."
        ),
        (
            f"The batch config hash is `{summary.batch_config_hash}`. Results are "
            "descriptive over five matched seeds; no significance claim is made."
        ),
        "",
        "## Matched-seed comparison",
        "",
            "| seed | GP best | Random best | GP-Random | GP source | Random source |",
            "|---:|---:|---:|---:|---|---|",
    ]
    for pair in summary.paired_differences:
        lines.append(
            f"| {pair.seed} | {pair.gp_score:.6f} | {pair.random_score:.6f} | "
            f"{pair.difference:+.6f} | `{pair.gp_source_run_id}` | "
            f"`{pair.random_source_run_id}` |"
        )
    lines.extend(
        [
            "",
            "## Aggregates and straight reference",
            "",
            f"Classic score: {summary.classic_score:.6f} from "
            f"`{summary.classic_source_run_id}`.",
            "",
            "| agent | mean best +/- sample SD | relative to classic | sources |",
            "|---|---:|---:|---|",
        ]
    )
    for aggregate in summary.aggregates:
        sources = ", ".join(f"`{item}`" for item in aggregate.source_run_ids)
        lines.append(
            f"| {aggregate.agent} | {aggregate.mean_best_score:.6f} +/- "
            f"{aggregate.sample_std_best_score:.6f} | "
            f"{aggregate.relative_to_classic:+.2%} | {sources} |"
        )
    gp_aggregate = next(item for item in summary.aggregates if item.agent == "gp")
    random_aggregate = next(
        item for item in summary.aggregates if item.agent == "random"
    )
    gp_wins = sum(item.difference > 0.0 for item in summary.paired_differences)
    mean_relative_to_random = (
        gp_aggregate.mean_best_score / random_aggregate.mean_best_score - 1.0
    )
    lines.extend(
        [
            "",
            (
                f"GP beat matched random in {gp_wins}/{len(summary.paired_differences)} "
                f"seeds; its mean best score was {mean_relative_to_random:+.2%} "
                "relative to random. These are descriptive matched-seed results, not "
                "a significance claim."
            ),
            (
                "The percentage ratios against classic are not interpreted as effect "
                "sizes because the corrected classic score is close to zero; the "
                "absolute scores and RF metrics are the meaningful comparison."
            ),
            "",
            "## Best-design RF sanity",
            "",
            "| source | min S11 dB | best VSWR | accepted-power gain dBi | realized gain dBi |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(
        (item for item in summary.rows if item.agent in {"gp", "random"}),
        key=lambda item: (item.agent, item.seed),
    ):
        lines.append(
            f"| `{row.source_run_id}` | {row.best_min_s11_db:.6f} | "
            f"{row.best_vswr:.4f} | {row.best_gain_dbi:.6f} | "
            f"{row.best_realized_gain_dbi:.6f} |"
        )
    maximum_raw = max(summary.rows, key=lambda row: row.best_gain_dbi)
    maximum_realized = max(
        summary.rows, key=lambda row: row.best_realized_gain_dbi
    )
    lines.extend(
        [
            "",
            (
                f"The largest accepted-power gain is {maximum_raw.best_gain_dbi:.6f} "
                f"dBi from `{maximum_raw.source_run_id}`; after terminal mismatch, "
                f"the largest realized gain is {maximum_realized.best_realized_gain_dbi:.6f} "
                f"dBi from `{maximum_realized.source_run_id}`. Lossless NEC2 "
                "efficiency is recorded but has zero score weight."
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## Native cross-solver checks",
            "",
            "| source | openEMS min (GHz, index, dB) | NEC2 min (GHz, index, dB) | gap | Pearson | verdict |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for check in summary.cross_checks:
        decision = check.decision
        if isinstance(decision, CurveDecisionV21):
            openems_min = (
                f"{decision.openems_validity.minimum_frequency_hz / 1e9:.6f}, "
                f"{decision.openems_validity.minimum_index}, "
                f"{decision.openems_validity.minimum_s11_db:.6f}"
            )
            nec2_min = (
                f"{decision.nec2_validity.minimum_frequency_hz / 1e9:.6f}, "
                f"{decision.nec2_validity.minimum_index}, "
                f"{decision.nec2_validity.minimum_s11_db:.6f}"
            )
        else:
            openems_min = f"legacy, {check.openems.resonance_s11_db:.6f}"
            nec2_min = f"legacy, {check.nec2.resonance_s11_db:.6f}"
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
        lines.append(
            f"| `{check.selected_design.source_run_id}` | {openems_min} | "
            f"{nec2_min} | {gap} | {correlation} | "
            f"{decision.verdict} (`{check.run_id}`) |"
        )
    lines.extend(["", "## Verdict", ""])
    if summary.verdict == "confirmed_improvement":
        improvement = summary.confirmed_improvement_fraction or 0.0
        lines.append(
            "`confirmed_improvement`: GP found a constrained meander dipole that "
            f"outperformed the box-straight reference by {improvement:.2%} in the "
            "NEC2 corrected exploration score, and the same native centerline passed "
            "protocol v2.1 in two independent solvers. This is not a claim that a new antenna "
            "was invented."
        )
    elif summary.verdict == "divergent":
        lines.append(
            "`divergent`: the top designs did not pass protocol v2.1. The NEC2 score "
            "advantage is retained as a solver-specific signal, not a confirmed result."
        )
    else:
        no_resonance = [
            check
            for check in summary.cross_checks
            if check.decision.verdict == "NO_RESONANCE_IN_BAND"
        ]
        if no_resonance:
            sources = ", ".join(f"`{check.run_id}`" for check in no_resonance)
            lines.append(
                "`insufficient_evidence`: protocol v2.1 returned "
                f"`NO_RESONANCE_IN_BAND` for {sources}. Agreement gap and Pearson "
                "were therefore not computed, and no improvement is confirmed."
            )
        else:
            lines.append(
                "`insufficient_evidence`: native cross-solver evidence is absent or "
                "does not yet unlock the preregistered positive verdict."
            )
    lines.extend(
        [
            "",
            "## Test skip audit",
            "",
            (
                "Day 3's six skips were the three tests in the real-NEC2 class and the "
                "three tests in the two-solver validation class. Their `skipif` guards "
                "are evaluated at collection time; the non-elevated managed shell could "
                "not create a WSL instance (`E_ACCESSDENIED`), so NEC2 appeared absent "
                "there even though experiment commands were run with the required WSL "
                "permission. In the current acceptance run, that permission is present "
                "at collection time and all six execute. This is a process-permission "
                "difference, not a scientific test defect; no skip guard was changed."
            ),
            "",
            "![Best-so-far curves](best-so-far.png)",
            "",
            "![Best GP geometry](best-geometry.png)",
            "",
        ]
    )
    return "\n".join(lines)


def analyze_wire_batch(batch_id: str, *, repo_root: Path) -> WireAnalysisSummary:
    """Generate JSON, Markdown, and figures for one archived wire batch."""

    batch = repo_root / "runs" / f"batch_{batch_id}"
    state = load_batch_state(batch / "state.json")
    document = load_batch_config(batch / "config.json")
    artifacts_root = repo_root / "artifacts" / "runs"
    summary = build_wire_analysis(
        state,
        document,
        artifacts_root=artifacts_root,
        cross_checks=_load_cross_checks(artifacts_root, batch_id),
    )
    output_name = "day4-wire" if batch_id == "day4-wire-v4" else batch_id
    output = repo_root / "artifacts" / "analysis" / output_name
    output.mkdir(parents=True, exist_ok=True)
    _write_text_lf(
        output / "summary.json",
        json.dumps(
            summary.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=True
        )
        + "\n",
    )
    _write_text_lf(output / "report.md", _report(summary))
    _plot_best_so_far(summary, output / "best-so-far.png")
    _plot_geometry(summary, artifacts_root, output / "best-geometry.png")
    return summary


def analyze_day5_wire_batch(
    batch_id: str, *, repo_root: Path
) -> Day5WireAnalysisSummary:
    """Build the Day 5 recovery-aware report without rewriting older artifacts."""

    batch = repo_root / "runs" / f"batch_{batch_id}"
    artifacts_root = repo_root / "artifacts" / "runs"
    final = build_wire_analysis(
        load_batch_state(batch / "state.json"),
        load_batch_config(batch / "config.json"),
        artifacts_root=artifacts_root,
        cross_checks=_load_cross_checks(artifacts_root, batch_id),
    )
    try:
        v5 = WireAnalysisSummary.model_validate_json(
            (
                repo_root
                / "artifacts"
                / "analysis"
                / "day4-wire-v5"
                / "summary.json"
            ).read_text(encoding="utf-8")
        )
        convergence = Day5ConvergenceSummary.model_validate_json(
            (
                artifacts_root
                / f"{batch_id}-convergence-top1"
                / "summary.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise WireAnalysisError(f"cannot load Day 5 supporting evidence: {error}") from error
    if final.verdict != "divergent":
        raise WireAnalysisError("Day 5 report expects the two completed divergent checks")
    summary = Day5WireAnalysisSummary(
        final_batch=final,
        v5_aggregates=v5.aggregates,
        convergence=convergence,
    )
    output = repo_root / "artifacts" / "analysis" / "day5-wire-v6"
    output.mkdir(parents=True, exist_ok=True)
    _write_text_lf(
        output / "summary.json",
        json.dumps(
            summary.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n",
    )
    _write_text_lf(output / "report.md", _day5_report(summary))
    _plot_best_so_far(final, output / "best-so-far.png")
    _plot_geometry(final, artifacts_root, output / "best-geometry.png")
    _plot_cross_solver_s11(final, output / "cross-solver-s11.png")
    _plot_segmentation_convergence(
        convergence, output / "segmentation-convergence.png"
    )
    return summary
