"""Source-addressed descriptive analysis for pixel-topology batches."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from matplotlib import pyplot as plt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.analysis import AnalysisError, _write_text_lf
from yaf_ai.exploration.batch import (
    BatchConfigDocument,
    BatchRunRecord,
    load_batch_config,
    load_batch_state,
)
from yaf_ai.exploration.pixel import PixelTopology, decode_mask_rle


class PixelLogRecord(BaseModel):
    """Accepted pixel evaluation fields consumed by the analysis."""

    model_config = ConfigDict(extra="allow", frozen=True)

    event_type: str = "evaluation"
    run_id: str
    step_index: int = Field(ge=0)
    solver_mode: str
    metrics: dict[str, float]
    score: float
    topology: PixelTopology


class PixelRunSummarySource(BaseModel):
    """Identity fields used to authenticate one run summary."""

    model_config = ConfigDict(extra="allow", frozen=True)

    run_id: str
    config_hash: str
    seed: int
    steps_completed: int = Field(ge=0)
    rejected_proposals: int = Field(default=0, ge=0)


class PixelRunRow(BaseModel):
    """One traceable best-result row for an agent/seed matrix cell."""

    model_config = ConfigDict(frozen=True)

    agent: str
    seed: int
    source_run_id: str
    config_hash: str
    best_score: float
    best_min_s11_db: float
    evaluations_to_best: int = Field(gt=0)
    best_so_far: tuple[float, ...]
    best_topology: PixelTopology
    solver_modes: tuple[str, ...]
    rejected_proposals: int = Field(ge=0)


class PixelAgentAggregate(BaseModel):
    """Mean and sample spread of best scores for one pixel proposer."""

    model_config = ConfigDict(frozen=True)

    agent: str
    count: int = Field(gt=0)
    mean_best_score: float
    sample_std_best_score: float
    source_run_ids: tuple[str, ...]


class PixelPairedDifference(BaseModel):
    """Matched evolve-minus-random best score for one seed."""

    model_config = ConfigDict(frozen=True)

    seed: int
    evolve_best_score: float
    random_best_score: float
    difference: float
    evolve_source_run_id: str
    random_source_run_id: str


class PixelQuestions(BaseModel):
    """Direct machine-readable answers requested by the Day 3 protocol."""

    model_config = ConfigDict(frozen=True)

    best_pixel_score: float
    best_pixel_source_run_id: str
    exceeds_day2_classic: bool
    day2_classic_score: float
    day2_classic_source_run_id: str
    exceeds_day2_parametric_gp: bool
    reaches_95_percent_of_day2_parametric_gp: bool
    fraction_of_day2_parametric_gp: float
    day2_parametric_gp_score: float
    day2_parametric_gp_source_run_id: str
    best_mask_iou_with_classic_rectangle: float
    best_mask_novelty_vs_classic_rectangle: float


class PixelBatchAnalysisSummary(BaseModel):
    """Machine-readable analysis with every derived number source-addressed."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str
    batch_config_hash: str
    batch_config: dict[str, Any]
    rows: tuple[PixelRunRow, ...]
    aggregates: tuple[PixelAgentAggregate, ...]
    paired_differences: tuple[PixelPairedDifference, ...]
    questions: PixelQuestions
    failed_runs: tuple[BatchRunRecord, ...]


def _load_pixel_log(path: Path, run_id: str) -> list[PixelLogRecord]:
    records: list[PixelLogRecord] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if payload.get("event_type") == "rejected":
                    continue
                records.append(PixelLogRecord.model_validate(payload))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise AnalysisError(f"invalid pixel log for {run_id}: {error}") from error
    records.sort(key=lambda record: record.step_index)
    if [record.step_index for record in records] != list(range(len(records))):
        raise AnalysisError(f"pixel log steps are not contiguous for {run_id}")
    if not records or any(record.run_id != run_id for record in records):
        raise AnalysisError(f"pixel log identity is invalid for {run_id}")
    modes = {record.solver_mode for record in records}
    if modes != {"subprocess"}:
        raise AnalysisError(
            f"pixel run {run_id} violates solver honesty: {sorted(modes)}"
        )
    return records


def _row(record: BatchRunRecord, runs_root: Path) -> PixelRunRow:
    directory = runs_root / record.run_id
    try:
        source_summary = PixelRunSummarySource.model_validate_json(
            (directory / "summary.json").read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise AnalysisError(
            f"invalid pixel summary for {record.run_id}: {error}"
        ) from error
    log_records = _load_pixel_log(directory / "log.jsonl", record.run_id)
    if (
        source_summary.run_id != record.run_id
        or source_summary.seed != record.seed
        or source_summary.steps_completed != len(log_records)
    ):
        raise AnalysisError(f"pixel source identity mismatch for {record.run_id}")
    best_index, best = max(enumerate(log_records), key=lambda item: item[1].score)
    running_best = float("-inf")
    best_so_far: list[float] = []
    for item in log_records:
        running_best = max(running_best, item.score)
        best_so_far.append(running_best)
    try:
        best_s11 = float(best.metrics["min_s11_db"])
    except KeyError as error:
        raise AnalysisError(f"pixel log lacks min_s11_db for {record.run_id}") from error
    return PixelRunRow(
        agent=record.agent,
        seed=record.seed,
        source_run_id=record.run_id,
        config_hash=source_summary.config_hash,
        best_score=best.score,
        best_min_s11_db=best_s11,
        evaluations_to_best=best_index + 1,
        best_so_far=tuple(best_so_far),
        best_topology=best.topology,
        solver_modes=tuple(item.solver_mode for item in log_records),
        rejected_proposals=source_summary.rejected_proposals,
    )


def build_pixel_analysis(
    document: BatchConfigDocument,
    records: tuple[BatchRunRecord, ...],
    *,
    runs_root: Path,
) -> PixelBatchAnalysisSummary:
    """Build descriptive pixel results from completed real-solver logs."""

    if document.config.experiment_kind != "pixel":
        raise AnalysisError("batch config is not a pixel experiment")
    matrix_records = tuple(
        record
        for record in records
        if record.status == "completed"
        and record.agent in {"evolve_pixel", "random_pixel"}
    )
    rows = tuple(_row(record, runs_root) for record in matrix_records)
    grouped: dict[str, list[PixelRunRow]] = defaultdict(list)
    for row in rows:
        grouped[row.agent].append(row)
    aggregates: list[PixelAgentAggregate] = []
    for agent, group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda item: item.seed)
        scores = [item.best_score for item in ordered]
        aggregates.append(
            PixelAgentAggregate(
                agent=agent,
                count=len(scores),
                mean_best_score=statistics.fmean(scores),
                sample_std_best_score=(
                    statistics.stdev(scores) if len(scores) > 1 else 0.0
                ),
                source_run_ids=tuple(item.source_run_id for item in ordered),
            )
        )
    indexed = {(row.agent, row.seed): row for row in rows}
    pairs: list[PixelPairedDifference] = []
    for seed in document.config.seeds:
        evolve = indexed.get(("evolve_pixel", seed))
        random = indexed.get(("random_pixel", seed))
        if evolve is None or random is None:
            continue
        pairs.append(
            PixelPairedDifference(
                seed=seed,
                evolve_best_score=evolve.best_score,
                random_best_score=random.best_score,
                difference=evolve.best_score - random.best_score,
                evolve_source_run_id=evolve.source_run_id,
                random_source_run_id=random.source_run_id,
            )
        )
    references = {item.label: item for item in document.config.reference_scores}
    classic = references["Day 2 wifi24 classic"]
    parametric = references["Day 2 wifi24 parametric GP best"]
    if not rows:
        raise AnalysisError("pixel analysis has no completed matrix rows")
    best = max(rows, key=lambda row: row.best_score)
    fraction = best.best_score / parametric.score
    questions = PixelQuestions(
        best_pixel_score=best.best_score,
        best_pixel_source_run_id=best.source_run_id,
        exceeds_day2_classic=best.best_score > classic.score,
        day2_classic_score=classic.score,
        day2_classic_source_run_id=classic.source_run_id,
        exceeds_day2_parametric_gp=best.best_score > parametric.score,
        reaches_95_percent_of_day2_parametric_gp=fraction >= 0.95,
        fraction_of_day2_parametric_gp=fraction,
        day2_parametric_gp_score=parametric.score,
        day2_parametric_gp_source_run_id=parametric.source_run_id,
        best_mask_iou_with_classic_rectangle=(
            best.best_topology.iou_vs_classic_rectangle
        ),
        best_mask_novelty_vs_classic_rectangle=(
            best.best_topology.novelty_vs_classic_rectangle
        ),
    )
    return PixelBatchAnalysisSummary(
        batch_id=document.config.batch_id,
        batch_config_hash=document.config_hash,
        batch_config=document.config.model_dump(mode="json"),
        rows=rows,
        aggregates=tuple(aggregates),
        paired_differences=tuple(pairs),
        questions=questions,
        failed_runs=tuple(record for record in records if record.status == "failed"),
    )


def _plot_curves(summary: PixelBatchAnalysisSummary, output_path: Path) -> None:
    figure, axis = plt.subplots(figsize=(8.5, 5.0))
    for agent, color, label in (
        ("evolve_pixel", "#6a1b9a", "(1+1) evolution"),
        ("random_pixel", "#00897b", "Constrained random"),
    ):
        rows = sorted(
            (row for row in summary.rows if row.agent == agent),
            key=lambda row: row.seed,
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
            mean_curve = [
                statistics.fmean(row.best_so_far[index] for row in rows)
                for index in range(length)
            ]
            axis.plot(
                range(1, length + 1),
                mean_curve,
                color=color,
                linewidth=2.6,
                label=f"{label} mean",
            )
    questions = summary.questions
    axis.axhline(
        questions.day2_classic_score,
        color="#455a64",
        linestyle="--",
        linewidth=1.7,
        label=f"Day 2 classic ({questions.day2_classic_source_run_id})",
    )
    axis.axhline(
        questions.day2_parametric_gp_score,
        color="#c62828",
        linestyle=":",
        linewidth=1.9,
        label=f"Day 2 parametric GP ({questions.day2_parametric_gp_source_run_id})",
    )
    axis.set_title("wifi24 pixel topology: best score so far")
    axis.set_xlabel("Evaluation number")
    axis.set_ylabel("Best composite score so far")
    axis.grid(alpha=0.2)
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def _plot_best_mask(summary: PixelBatchAnalysisSummary, output_path: Path) -> None:
    best = max(summary.rows, key=lambda row: row.best_score)
    topology = best.best_topology
    mask = decode_mask_rle(topology.rle, topology.rows, topology.columns)
    figure, axis = plt.subplots(figsize=(5.2, 5.2))
    axis.imshow(mask.T, origin="lower", cmap="copper", interpolation="nearest")
    axis.set_title(
        f"Best pixel mask: {best.source_run_id}\n"
        f"score={best.best_score:.6f}, novelty={topology.novelty_vs_classic_rectangle:.3f}"
    )
    axis.set_xlabel("x pixel")
    axis.set_ylabel("y pixel")
    axis.set_xticks(range(0, topology.rows, 2))
    axis.set_yticks(range(0, topology.columns, 2))
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def _report(summary: PixelBatchAnalysisSummary) -> str:
    config = summary.batch_config
    lines = [
        f"# Batch {summary.batch_id}: wifi24 pixel topology",
        "",
        "## Frozen scope",
        "",
        (
            f"This descriptive comparison uses seeds {config['seeds']} and "
            f"budget={config['budget']} after a measured preflight. All accepted "
            "evaluations must be openEMS subprocess runs; no significance test is claimed."
        ),
        (
            f"The proposal space is `{config['proposal_space']['version']}` with a "
            f"{config['proposal_space']['rows']}x{config['proposal_space']['columns']} "
            f"grid and minimum feature {config['proposal_space']['pixel_size_m'] * 1e3:.3f} mm."
        ),
        "",
        "## Matched results",
        "",
        "| Seed | Evolution best | Random best | Difference | Sources |",
        "|---:|---:|---:|---:|---|",
    ]
    for pair in summary.paired_differences:
        lines.append(
            f"| {pair.seed} | {pair.evolve_best_score:.6f} | "
            f"{pair.random_best_score:.6f} | {pair.difference:+.6f} | "
            f"`{pair.evolve_source_run_id}`, `{pair.random_source_run_id}` |"
        )
    lines.extend(
        [
            "",
            "## Descriptive aggregates",
            "",
            "| Agent | Mean best +/- sample SD | Source runs |",
            "|---|---:|---|",
        ]
    )
    for aggregate in summary.aggregates:
        sources = ", ".join(f"`{item}`" for item in aggregate.source_run_ids)
        lines.append(
            f"| {aggregate.agent} | {aggregate.mean_best_score:.6f} +/- "
            f"{aggregate.sample_std_best_score:.6f} | {sources} |"
        )
    questions = summary.questions
    classic_answer = "yes" if questions.exceeds_day2_classic else "no"
    gp_exceeded = "yes" if questions.exceeds_day2_parametric_gp else "no"
    gp_approached = (
        "yes" if questions.reaches_95_percent_of_day2_parametric_gp else "no"
    )
    lines.extend(
        [
            "",
            "## Direct answers",
            "",
            (
                f"1. **Can pixel topology exceed classic? {classic_answer}.** The best "
                f"pixel score is {questions.best_pixel_score:.6f} from "
                f"`{questions.best_pixel_source_run_id}` versus "
                f"{questions.day2_classic_score:.6f} from "
                f"`{questions.day2_classic_source_run_id}`."
            ),
            (
                f"2. **Does it approach or exceed the Day 2 parametric GP best?** "
                f"Reached 95%: {gp_approached}; exceeded: {gp_exceeded}. The best pixel "
                f"score is {questions.fraction_of_day2_parametric_gp:.2%} of "
                f"{questions.day2_parametric_gp_score:.6f} from "
                f"`{questions.day2_parametric_gp_source_run_id}`."
            ),
            (
                f"3. **How different is the best mask?** IoU with the frozen classic "
                f"rectangle is {questions.best_mask_iou_with_classic_rectangle:.3f}; "
                f"novelty `1-IoU` is "
                f"{questions.best_mask_novelty_vs_classic_rectangle:.3f}."
            ),
            "",
            "These are topology-exploration outcomes, not a claim that a new antenna was invented.",
            "",
            "## Curves and topology",
            "",
            "![Pixel best-so-far](wifi24-best-so-far.png)",
            "",
            "![Best pixel topology](best-pixel-mask.png)",
            "",
        ]
    )
    if summary.failed_runs:
        lines.extend(["## Failed runs", ""])
        for record in summary.failed_runs:
            lines.append(f"- `{record.run_id}`: {record.error}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def analyze_pixel_batch(
    batch_id: str,
    *,
    repo_root: Path,
) -> PixelBatchAnalysisSummary:
    """Generate JSON, Markdown, curve, and topology artifacts for a pixel batch."""

    batch_directory = repo_root / "runs" / f"batch_{batch_id}"
    state = load_batch_state(batch_directory / "state.json")
    document = load_batch_config(batch_directory / "config.json")
    if state.config_hash != document.config_hash:
        raise AnalysisError("pixel state and config hashes do not match")
    summary = build_pixel_analysis(
        document,
        state.runs,
        runs_root=repo_root / "runs",
    )
    output = repo_root / "artifacts" / "analysis" / batch_id
    output.mkdir(parents=True, exist_ok=True)
    _write_text_lf(
        output / "summary.json",
        json.dumps(
            summary.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
    )
    _write_text_lf(output / "report.md", _report(summary))
    _plot_curves(summary, output / "wifi24-best-so-far.png")
    _plot_best_mask(summary, output / "best-pixel-mask.png")
    return summary
