"""Source-backed analysis for the Day 6.5 ES versus random hunt."""

from __future__ import annotations

import json
import os
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import matplotlib
from pydantic import BaseModel, ConfigDict, Field

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from yaf_ai.exploration.batch import BatchState  # noqa: E402
from yaf_ai.exploration.cross_check import CrossCheckError  # noqa: E402
from yaf_ai.exploration.day65_batch import (  # noqa: E402
    DAY65_BATCH_ID,
    DAY65_BUDGET,
    DAY65_OCFD_RUN_ID,
    DAY65_OCFD_SCORE,
    DAY65_SEEDS,
)
from yaf_ai.exploration.day65_cross_check import (  # noqa: E402
    Day65V2ConvergenceDocument,
    Day65V2CrossCheckRunSummary,
    load_day65_v2_convergence,
    reconstruct_day65_v2_design,
)
from yaf_ai.exploration.day65_selection import (  # noqa: E402
    Day65SelectionDocument,
    load_day65_selection,
)
from yaf_ai.exploration.logger import AuditStepRecord  # noqa: E402

DAY65_V2_OUTPUT = f"artifacts/analysis/{DAY65_BATCH_ID}"
DAY65_ABSOLUTE_ANCHOR_RELEASED = False

StaticFinalVerdict = Literal["confirmed_improvement", "insufficient_evidence"]


class Day65V2BatchRow(BaseModel):
    """One source-addressed seed winner selected by unshaped score."""

    model_config = ConfigDict(frozen=True)

    agent: str
    seed: int
    source_run_id: str
    source_step_index: int = Field(ge=0)
    source_geometry_hash: str
    base_score: float
    search_score: float
    valid_both_bands: bool
    band_24_min_s11_db: float
    band_24_frequency_hz: float = Field(gt=0.0)
    band_58_min_s11_db: float
    band_58_frequency_hz: float = Field(gt=0.0)
    duration_seconds: float = Field(ge=0.0)
    rejected_proposals: int = Field(ge=0)


class Day65V2AgentAggregate(BaseModel):
    """Descriptive statistics over the three preregistered seeds."""

    model_config = ConfigDict(frozen=True)

    agent: str
    source_run_ids: tuple[str, ...]
    mean_best_base_score: float
    sample_standard_deviation: float = Field(ge=0.0)
    valid_both_band_winners: int = Field(ge=0)


class Day65V2PairDifference(BaseModel):
    """Matched ES-minus-random best-base-score difference."""

    model_config = ConfigDict(frozen=True)

    seed: int
    es_source_run_id: str
    random_source_run_id: str
    es_score: float
    random_score: float
    difference: float


class Day65V2AnalysisSummary(BaseModel):
    """Machine-readable analysis of every v2 run and final check."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str = DAY65_BATCH_ID
    budget: int = DAY65_BUDGET
    seeds: tuple[int, ...] = DAY65_SEEDS
    ocfd_source_run_id: str = DAY65_OCFD_RUN_ID
    ocfd_score: float = DAY65_OCFD_SCORE
    rows: tuple[Day65V2BatchRow, ...]
    aggregates: tuple[Day65V2AgentAggregate, ...]
    paired_differences: tuple[Day65V2PairDifference, ...]
    selection: Day65SelectionDocument
    convergence: Day65V2ConvergenceDocument
    cross_checks: tuple[
        Day65V2CrossCheckRunSummary,
        Day65V2CrossCheckRunSummary,
    ]
    absolute_anchor_released: bool = DAY65_ABSOLUTE_ANCHOR_RELEASED
    candidate_level_confirmation: bool
    final_verdict: StaticFinalVerdict


def apply_static_anchor_ceiling(
    *, candidate_level_confirmation: bool, absolute_anchor_released: bool
) -> StaticFinalVerdict:
    """Apply the preregistered absolute-anchor ceiling to the static study."""

    if candidate_level_confirmation and absolute_anchor_released:
        return "confirmed_improvement"
    return "insufficient_evidence"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _load_records(path: Path) -> tuple[AuditStepRecord, ...]:
    records: list[AuditStepRecord] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            if raw.get("event_type") == "evaluation":
                records.append(AuditStepRecord.model_validate(raw))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot load v2 evidence {path}: {error}") from error
    if len(records) != DAY65_BUDGET:
        raise CrossCheckError(
            f"v2 evidence {path} has {len(records)} accepted rows, expected {DAY65_BUDGET}"
        )
    if any(record.solver_mode != "subprocess" for record in records):
        raise CrossCheckError(f"v2 evidence {path} contains a fallback")
    return tuple(records)


def _load_batch_state(repo_root: Path) -> BatchState:
    path = repo_root / DAY65_V2_OUTPUT / "state.json"
    try:
        state = BatchState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CrossCheckError(f"cannot load v2 batch state: {error}") from error
    if len(state.runs) != 6 or any(record.status != "completed" for record in state.runs):
        raise CrossCheckError("all six v2 matrix cells must be complete")
    return state


def _best_record(records: Sequence[AuditStepRecord]) -> AuditStepRecord:
    return min(records, key=lambda row: (-row.score, row.run_id, row.step_index))


def _batch_rows(
    repo_root: Path, state: BatchState
) -> tuple[tuple[Day65V2BatchRow, ...], dict[str, tuple[AuditStepRecord, ...]]]:
    runs = repo_root / "artifacts" / "runs"
    logs: dict[str, tuple[AuditStepRecord, ...]] = {}
    rows: list[Day65V2BatchRow] = []
    for agent in ("es", "random"):
        for seed in DAY65_SEEDS:
            run_id = f"{DAY65_BATCH_ID}-dual-{agent}-s{seed}"
            records = _load_records(runs / run_id / "log.jsonl")
            logs[run_id] = records
            best = _best_record(records)
            state_record = next(
                (record for record in state.runs if record.run_id == run_id), None
            )
            if state_record is None or state_record.duration_seconds is None:
                raise CrossCheckError(f"batch state lacks duration for {run_id}")
            try:
                run_summary = json.loads(
                    (runs / run_id / "summary.json").read_text(encoding="utf-8")
                )
                rejected = int(run_summary["rejected_proposals"])
            except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
                raise CrossCheckError(f"cannot load run summary {run_id}: {error}") from error
            rows.append(
                Day65V2BatchRow(
                    agent=agent,
                    seed=seed,
                    source_run_id=run_id,
                    source_step_index=best.step_index,
                    source_geometry_hash=best.geometry_hash,
                    base_score=best.score,
                    search_score=best.metrics["search_score"],
                    valid_both_bands=bool(best.metrics["valid_both_bands"]),
                    band_24_min_s11_db=best.metrics["band_24_min_s11_db"],
                    band_24_frequency_hz=best.metrics["band_24_frequency_hz"],
                    band_58_min_s11_db=best.metrics["band_58_min_s11_db"],
                    band_58_frequency_hz=best.metrics["band_58_frequency_hz"],
                    duration_seconds=state_record.duration_seconds,
                    rejected_proposals=rejected,
                )
            )
    return tuple(rows), logs


def build_day65_v2_analysis(
    repo_root: Path,
) -> tuple[Day65V2AnalysisSummary, dict[str, tuple[AuditStepRecord, ...]]]:
    """Load every source row and produce descriptive comparisons only."""

    state = _load_batch_state(repo_root)
    rows, logs = _batch_rows(repo_root, state)
    aggregates: list[Day65V2AgentAggregate] = []
    for agent in ("es", "random"):
        selected = tuple(row for row in rows if row.agent == agent)
        scores = [row.base_score for row in selected]
        aggregates.append(
            Day65V2AgentAggregate(
                agent=agent,
                source_run_ids=tuple(row.source_run_id for row in selected),
                mean_best_base_score=statistics.fmean(scores),
                sample_standard_deviation=statistics.stdev(scores),
                valid_both_band_winners=sum(row.valid_both_bands for row in selected),
            )
        )
    pairs: list[Day65V2PairDifference] = []
    for seed in DAY65_SEEDS:
        es = next(row for row in rows if row.agent == "es" and row.seed == seed)
        random = next(row for row in rows if row.agent == "random" and row.seed == seed)
        pairs.append(
            Day65V2PairDifference(
                seed=seed,
                es_source_run_id=es.source_run_id,
                random_source_run_id=random.source_run_id,
                es_score=es.base_score,
                random_score=random.base_score,
                difference=es.base_score - random.base_score,
            )
        )
    selection = load_day65_selection(repo_root)
    convergence = load_day65_v2_convergence(repo_root)
    checks: list[Day65V2CrossCheckRunSummary] = []
    for rank in (1, 2):
        run_id = f"day65-freeform-v2-final-crosscheck-top{rank}"
        try:
            checks.append(
                Day65V2CrossCheckRunSummary.model_validate_json(
                    (
                        repo_root
                        / "artifacts"
                        / "runs"
                        / run_id
                        / "summary.json"
                    ).read_text(encoding="utf-8")
                )
            )
        except (OSError, ValueError) as error:
            raise CrossCheckError(f"cannot load final v2 run {run_id}: {error}") from error
    candidate_level_confirmation = any(
        check.discovery_verdict == "confirmed_improvement" for check in checks
    )
    final = apply_static_anchor_ceiling(
        candidate_level_confirmation=candidate_level_confirmation,
        absolute_anchor_released=DAY65_ABSOLUTE_ANCHOR_RELEASED,
    )
    summary = Day65V2AnalysisSummary(
        rows=rows,
        aggregates=(aggregates[0], aggregates[1]),
        paired_differences=tuple(pairs),
        selection=selection,
        convergence=convergence,
        cross_checks=(checks[0], checks[1]),
        absolute_anchor_released=DAY65_ABSOLUTE_ANCHOR_RELEASED,
        candidate_level_confirmation=candidate_level_confirmation,
        final_verdict=final,
    )
    return summary, logs


def _plot_best_so_far(
    output: Path,
    logs: dict[str, tuple[AuditStepRecord, ...]],
    summary: Day65V2AnalysisSummary,
) -> None:
    figure, axis = plt.subplots(figsize=(9.5, 5.8))
    colors = {"es": "#1769aa", "random": "#d97706"}
    for agent in ("es", "random"):
        all_curves: list[list[float]] = []
        for seed in DAY65_SEEDS:
            run_id = f"{DAY65_BATCH_ID}-dual-{agent}-s{seed}"
            running = -float("inf")
            curve: list[float] = []
            for record in logs[run_id]:
                running = max(running, record.score)
                curve.append(running)
            all_curves.append(curve)
            axis.plot(
                range(1, len(curve) + 1),
                curve,
                color=colors[agent],
                alpha=0.22,
                linewidth=0.8,
            )
        mean_curve = np.mean(np.asarray(all_curves), axis=0)
        axis.plot(
            range(1, len(mean_curve) + 1),
            mean_curve,
            color=colors[agent],
            linewidth=2.2,
            label=f"{agent} mean",
        )
    axis.axhline(summary.ocfd_score, color="black", linestyle="--", label="OCFD optimum")
    axis.set_xlabel("Accepted evaluation")
    axis.set_ylabel("Best-so-far unshaped worst-band score")
    axis.set_title("Day 6.5 free-form dual-band hunt")
    axis.grid(alpha=0.2)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "best-so-far.png", dpi=180)
    plt.close(figure)


def _plot_geometry(repo_root: Path, output: Path, summary: Day65V2AnalysisSummary) -> None:
    figure = plt.figure(figsize=(12.0, 8.0))
    for row, candidate in enumerate(summary.selection.candidates):
        geometry, _seed = reconstruct_day65_v2_design(repo_root, candidate)
        iso = figure.add_subplot(2, 2, row * 2 + 1, projection="3d")
        xy = figure.add_subplot(2, 2, row * 2 + 2)
        for start_index, stop_index in geometry.faces[1:]:
            start = geometry.vertices[start_index]
            stop = geometry.vertices[stop_index]
            iso.plot(
                [start[0] * 1e3, stop[0] * 1e3],
                [start[1] * 1e3, stop[1] * 1e3],
                [start[2] * 1e3, stop[2] * 1e3],
                color="#1769aa",
                linewidth=1.3,
            )
            xy.plot(
                [start[0] * 1e3, stop[0] * 1e3],
                [start[1] * 1e3, stop[1] * 1e3],
                color="#1769aa",
                linewidth=1.3,
            )
        iso.set(xlim=(-20, 20), ylim=(-20, 20), zlim=(-20, 20))
        iso.set_title(f"Top {candidate.rank} 3D")
        xy.set(xlim=(-20, 20), ylim=(-20, 20), aspect="equal")
        xy.set_title(f"Top {candidate.rank} xy projection")
        xy.grid(alpha=0.2)
    figure.suptitle("Frozen Day 6.5 v2 top-two geometries")
    figure.tight_layout()
    figure.savefig(output / "top-geometries-3d.png", dpi=180)
    plt.close(figure)


def _plot_cross_checks(output: Path, summary: Day65V2AnalysisSummary) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(10.0, 8.0), sharex=True)
    for axis, check in zip(axes, summary.cross_checks, strict=True):
        for label, curve, color in (
            ("NEC2 lambda/160", check.nec2, "#1769aa"),
            ("openEMS released 6x", check.openems, "#d97706"),
        ):
            axis.plot(
                np.asarray(curve.frequency_hz) / 1e9,
                curve.s11_db,
                label=label,
                color=color,
                linewidth=1.6,
            )
        axis.axvspan(2.40, 2.50, color="#60a5fa", alpha=0.16)
        axis.axvspan(5.725, 5.875, color="#f59e0b", alpha=0.16)
        axis.axhline(-6.0, color="black", linestyle=":", linewidth=1.0)
        axis.set_ylabel("S11 (dB)")
        axis.set_title(
            f"Top {check.selected_design.rank}: {check.decision.verdict}; "
            f"Pearson={check.decision.whole_sweep_pearson}"
        )
        axis.grid(alpha=0.2)
        axis.legend(fontsize=8)
    axes[-1].set_xlabel("Frequency (GHz)")
    figure.tight_layout()
    figure.savefig(output / "dual-solver-s11.png", dpi=180)
    plt.close(figure)


def _report(summary: Day65V2AnalysisSummary) -> str:
    lines = [
        "# Day 6.5 free-form v2 dual-band hunt",
        "",
        f"Final verdict: `{summary.final_verdict}`.",
        "All descriptive comparisons use unshaped base score; the +0.25 validity "
        "bonus affected ES search feedback only.",
        "",
        "## Batch comparison",
        "",
        "| agent | seed | best base | search score | both valid | 2.4 S11 | 5.8 S11 | elapsed | rejected | source |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---|",
    ]
    for row in summary.rows:
        lines.append(
            f"| {row.agent} | {row.seed} | {row.base_score:.9f} | "
            f"{row.search_score:.9f} | {row.valid_both_bands} | "
            f"{row.band_24_min_s11_db:.6f} dB | {row.band_58_min_s11_db:.6f} dB | "
            f"{row.duration_seconds:.3f} s | {row.rejected_proposals} | "
            f"`{row.source_run_id}` step {row.source_step_index} |"
        )
    lines.extend(["", "Descriptive n=3 aggregates (no significance test):", ""])
    for aggregate in summary.aggregates:
        lines.append(
            f"- {aggregate.agent}: {aggregate.mean_best_base_score:.9f} +/- "
            f"{aggregate.sample_standard_deviation:.9f} sample SD; "
            f"valid-both winner count {aggregate.valid_both_band_winners}/3."
        )
    lines.append(
        "- Paired ES-minus-random: "
        + ", ".join(
            f"seed {row.seed}: {row.difference:+.9f}"
            for row in summary.paired_differences
        )
        + "."
    )
    lines.extend([
        "",
        f"OCFD anchor `{summary.ocfd_source_run_id}`: {summary.ocfd_score:.9f}.",
        "",
        "## Frozen top-two and instrument convergence",
        "",
    ])
    for candidate in summary.selection.candidates:
        lines.append(
            f"- Top {candidate.rank}: `{candidate.source_run_id}` step "
            f"{candidate.source_step_index}, base {candidate.source_base_score:.9f}, "
            f"geometry `{candidate.source_geometry_hash}`."
        )
    lines.extend([
        "",
        f"Source-specific high-band self-convergence: "
        f"`{summary.convergence.self_convergence_established}`; first passing "
        f"refinement `{summary.convergence.first_passing_refinement}`; released claim "
        "instrument `6x/240k`.",
        "",
        "## Final v2.1 cross-checks",
        "",
        "| top | band | NEC2 f/S11/valid | openEMS f/S11/valid | gap |",
        "|---:|---|---|---|---:|",
    ])
    for check in summary.cross_checks:
        for name, band in (("2.4 GHz", check.decision.low_band), ("5.8 GHz", check.decision.high_band)):
            lines.append(
                f"| {check.selected_design.rank} | {name} | "
                f"{band.nec2.minimum_frequency_hz / 1e9:.3f} GHz / "
                f"{band.nec2.minimum_s11_db:.6f} dB / {band.nec2.valid} | "
                f"{band.openems.minimum_frequency_hz / 1e9:.3f} GHz / "
                f"{band.openems.minimum_s11_db:.6f} dB / {band.openems.valid} | "
                f"{band.resonance_relative_difference} |"
            )
        lines.append(
            f"| {check.selected_design.rank} | whole sweep | lambda/160 | 6x/240k | "
            f"Pearson {check.decision.whole_sweep_pearson}; verdict "
            f"`{check.decision.verdict}`; discovery `{check.discovery_verdict}` |"
        )
    lines.extend([
        "",
        "A negative outcome means only that the current frozen space, optimizer "
        "definition, and budget did not produce a dual-band design meeting every "
        "pre-registered cross-solver gate; it does not justify weakening a threshold.",
        "",
        "![Best-so-far](best-so-far.png)",
        "",
        "![Frozen top geometries](top-geometries-3d.png)",
        "",
        "![Dual-solver S11](dual-solver-s11.png)",
        "",
    ])
    return "\n".join(lines)


def write_day65_v2_analysis(repo_root: Path) -> Day65V2AnalysisSummary:
    """Write JSON, report, and source-backed figures."""

    summary, logs = build_day65_v2_analysis(repo_root)
    output = repo_root / DAY65_V2_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "summary.json", summary.model_dump(mode="json"))
    (output / "report.md").write_bytes((_report(summary) + "\n").encode("utf-8"))
    _plot_best_so_far(output, logs, summary)
    _plot_geometry(repo_root, output, summary)
    _plot_cross_checks(output, summary)
    return summary
