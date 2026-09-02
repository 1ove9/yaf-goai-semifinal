"""Traceable descriptive analysis for exploration batches."""

from __future__ import annotations

import json
import os
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "yaf-matplotlib"),
)
import matplotlib  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, ValidationError  # noqa: E402

from yaf_ai.exploration.batch import (  # noqa: E402
    BatchConfigDocument,
    BatchRunRecord,
    BatchState,
    load_batch_config,
    load_batch_state,
)

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

DAY1_WIFI24_CONFIG_HASH = (
    "6996470edd01ad8c2a2141dc07172064fef74efcf8184a4651968a0b153851f7"
)


class AnalysisError(RuntimeError):
    """Raised when source evidence is incomplete or scientifically invalid."""


class AnalysisLogRecord(BaseModel):
    """Subset of one JSONL record required for batch analysis."""

    model_config = ConfigDict(extra="allow", frozen=True)

    run_id: str
    step_index: int = Field(ge=0)
    solver_mode: str
    metrics: dict[str, float]
    score: float


class AnalysisRunSummary(BaseModel):
    """Subset of a run summary needed to cross-check analysis inputs."""

    model_config = ConfigDict(extra="allow", frozen=True)

    run_id: str
    config_hash: str
    seed: int
    steps_completed: int = Field(ge=0)


class RunDataRow(BaseModel):
    """One source-addressed row for a completed matrix run."""

    model_config = ConfigDict(frozen=True)

    spec: str
    agent: str
    seed: int
    source_run_id: str
    config_hash: str
    best_score: float
    best_min_s11_db: float
    evaluations_to_best: int = Field(gt=0)
    best_so_far: tuple[float, ...]
    solver_modes: tuple[str, ...]


class AgentAggregate(BaseModel):
    """Descriptive statistics for matched best scores."""

    model_config = ConfigDict(frozen=True)

    spec: str
    agent: str
    count: int = Field(gt=0)
    mean_best_score: float
    sample_std_best_score: float
    source_run_ids: tuple[str, ...]


class PairedDifference(BaseModel):
    """One GP-minus-random best-score difference for a matched seed."""

    model_config = ConfigDict(frozen=True)

    spec: str
    seed: int
    gp_best_score: float
    random_best_score: float
    difference: float
    gp_source_run_id: str
    random_source_run_id: str


class ClassicComparison(BaseModel):
    """Agent mean improvement relative to the single classic reference."""

    model_config = ConfigDict(frozen=True)

    spec: str
    agent: str
    agent_mean_best_score: float
    classic_score: float
    improvement_fraction: float
    agent_source_run_ids: tuple[str, ...]
    classic_source_run_id: str


class DiscoveryDecision(BaseModel):
    """Honest per-spec assessment against the frozen discovery policy."""

    model_config = ConfigDict(frozen=True)

    spec: str
    matched_seed_count: int = Field(ge=0)
    gp_wins: int = Field(ge=0)
    random_wins: int = Field(ge=0)
    ties: int = Field(ge=0)
    gp_vs_classic_improvement_fraction: float
    improvement_threshold: float
    improvement_threshold_met: bool
    cross_solver_status: Literal["pending"] = "pending"
    stable_negative: bool
    verdict: Literal["negative", "insufficient_evidence"]
    reason: str
    source_run_ids: tuple[str, ...]


class BatchAnalysisSummary(BaseModel):
    """Machine-readable, source-addressed analysis artifact."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str
    batch_config_hash: str
    batch_config: dict[str, Any]
    rows: tuple[RunDataRow, ...]
    aggregates: tuple[AgentAggregate, ...]
    paired_differences: tuple[PairedDifference, ...]
    classic_comparisons: tuple[ClassicComparison, ...]
    discovery_decisions: tuple[DiscoveryDecision, ...]
    failed_runs: tuple[BatchRunRecord, ...]


def _write_text_lf(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
    os.replace(temporary, path)


def _load_log(path: Path, run_id: str) -> list[AnalysisLogRecord]:
    records: list[AnalysisLogRecord] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(AnalysisLogRecord.model_validate_json(line))
    except (OSError, ValidationError) as error:
        raise AnalysisError(f"invalid source log for {run_id}: {error}") from error
    records.sort(key=lambda record: record.step_index)
    if not records:
        raise AnalysisError(f"source log is empty for {run_id}")
    if [record.step_index for record in records] != list(range(len(records))):
        raise AnalysisError(f"source log steps are not contiguous for {run_id}")
    if any(record.run_id != run_id for record in records):
        raise AnalysisError(f"source log run_id mismatch for {run_id}")
    modes = {record.solver_mode for record in records}
    if modes != {"subprocess"}:
        raise AnalysisError(
            f"run {run_id} violates Day 2 solver honesty requirement: {sorted(modes)}"
        )
    return records


def _row_from_record(record: BatchRunRecord, runs_root: Path) -> RunDataRow:
    run_directory = runs_root / record.run_id
    try:
        summary = AnalysisRunSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise AnalysisError(
            f"invalid source summary for {record.run_id}: {error}"
        ) from error
    if summary.run_id != record.run_id or summary.seed != record.seed:
        raise AnalysisError(f"source summary identity mismatch for {record.run_id}")
    log_records = _load_log(run_directory / "log.jsonl", record.run_id)
    if summary.steps_completed != len(log_records):
        raise AnalysisError(f"summary step count mismatch for {record.run_id}")

    best_index, best = max(
        enumerate(log_records),
        key=lambda item: item[1].score,
    )
    best_so_far: list[float] = []
    running_best = float("-inf")
    for item in log_records:
        running_best = max(running_best, item.score)
        best_so_far.append(running_best)
    try:
        best_s11 = min(item.metrics["min_s11_db"] for item in log_records)
    except KeyError as error:
        raise AnalysisError(
            f"source log lacks min_s11_db for {record.run_id}"
        ) from error
    return RunDataRow(
        spec=record.spec_name,
        agent=record.agent,
        seed=record.seed,
        source_run_id=record.run_id,
        config_hash=summary.config_hash,
        best_score=best.score,
        best_min_s11_db=best_s11,
        evaluations_to_best=best_index + 1,
        best_so_far=tuple(best_so_far),
        solver_modes=tuple(item.solver_mode for item in log_records),
    )


def _aggregates(rows: tuple[RunDataRow, ...]) -> tuple[AgentAggregate, ...]:
    grouped: dict[tuple[str, str], list[RunDataRow]] = defaultdict(list)
    for row in rows:
        if row.agent in {"gp", "random"}:
            grouped[(row.spec, row.agent)].append(row)
    results: list[AgentAggregate] = []
    for (spec, agent), group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda row: row.seed)
        scores = [row.best_score for row in ordered]
        results.append(
            AgentAggregate(
                spec=spec,
                agent=agent,
                count=len(scores),
                mean_best_score=statistics.fmean(scores),
                sample_std_best_score=(statistics.stdev(scores) if len(scores) > 1 else 0.0),
                source_run_ids=tuple(row.source_run_id for row in ordered),
            )
        )
    return tuple(results)


def _paired_differences(rows: tuple[RunDataRow, ...]) -> tuple[PairedDifference, ...]:
    indexed = {(row.spec, row.agent, row.seed): row for row in rows}
    pairs: list[PairedDifference] = []
    keys = sorted(
        (row.spec, row.seed)
        for row in rows
        if row.agent == "gp"
    )
    for spec, seed in keys:
        gp = indexed[(spec, "gp", seed)]
        random = indexed.get((spec, "random", seed))
        if random is None:
            continue
        pairs.append(
            PairedDifference(
                spec=spec,
                seed=seed,
                gp_best_score=gp.best_score,
                random_best_score=random.best_score,
                difference=gp.best_score - random.best_score,
                gp_source_run_id=gp.source_run_id,
                random_source_run_id=random.source_run_id,
            )
        )
    return tuple(pairs)


def _classic_comparisons(
    rows: tuple[RunDataRow, ...],
    aggregates: tuple[AgentAggregate, ...],
) -> tuple[ClassicComparison, ...]:
    classic = {row.spec: row for row in rows if row.agent == "classic"}
    comparisons: list[ClassicComparison] = []
    for aggregate in aggregates:
        reference = classic.get(aggregate.spec)
        if reference is None:
            continue
        if reference.best_score == 0.0:
            raise AnalysisError(f"classic score is zero for {aggregate.spec}")
        comparisons.append(
            ClassicComparison(
                spec=aggregate.spec,
                agent=aggregate.agent,
                agent_mean_best_score=aggregate.mean_best_score,
                classic_score=reference.best_score,
                improvement_fraction=(
                    aggregate.mean_best_score / reference.best_score - 1.0
                ),
                agent_source_run_ids=aggregate.source_run_ids,
                classic_source_run_id=reference.source_run_id,
            )
        )
    return tuple(comparisons)


def _decisions(
    document: BatchConfigDocument,
    pairs: tuple[PairedDifference, ...],
    comparisons: tuple[ClassicComparison, ...],
) -> tuple[DiscoveryDecision, ...]:
    policy = document.config.discovery_policy
    results: list[DiscoveryDecision] = []
    for spec in document.config.specs:
        spec_pairs = [pair for pair in pairs if pair.spec == spec]
        gp_comparison = next(
            comparison
            for comparison in comparisons
            if comparison.spec == spec and comparison.agent == "gp"
        )
        stable_negative = (
            len(spec_pairs) >= policy.minimum_negative_samples
            and all(pair.difference < 0.0 for pair in spec_pairs)
        )
        improvement_met = (
            gp_comparison.improvement_fraction
            >= policy.classic_improvement_fraction
        )
        if stable_negative:
            verdict: Literal["negative", "insufficient_evidence"] = "negative"
            reason = (
                "GP trails matched random search for every seed and meets the "
                "predeclared minimum negative-sample count."
            )
        else:
            verdict = "insufficient_evidence"
            reason = (
                "Descriptive evidence is not a stable negative signal, and positive "
                "discovery remains blocked pending cross-solver verification."
            )
        source_ids = [gp_comparison.classic_source_run_id]
        for pair in spec_pairs:
            source_ids.extend([pair.gp_source_run_id, pair.random_source_run_id])
        results.append(
            DiscoveryDecision(
                spec=spec,
                matched_seed_count=len(spec_pairs),
                gp_wins=sum(pair.difference > 0.0 for pair in spec_pairs),
                random_wins=sum(pair.difference < 0.0 for pair in spec_pairs),
                ties=sum(pair.difference == 0.0 for pair in spec_pairs),
                gp_vs_classic_improvement_fraction=(
                    gp_comparison.improvement_fraction
                ),
                improvement_threshold=policy.classic_improvement_fraction,
                improvement_threshold_met=improvement_met,
                stable_negative=stable_negative,
                verdict=verdict,
                reason=reason,
                source_run_ids=tuple(dict.fromkeys(source_ids)),
            )
        )
    return tuple(results)


def build_analysis(
    state: BatchState,
    document: BatchConfigDocument,
    *,
    runs_root: Path,
) -> BatchAnalysisSummary:
    """Build source-addressed descriptive statistics from completed JSONL logs."""

    if state.config_hash != document.config_hash:
        raise AnalysisError("batch state and config hashes do not match")
    rows = tuple(
        _row_from_record(record, runs_root)
        for record in state.runs
        if record.status == "completed"
    )
    aggregates = _aggregates(rows)
    pairs = _paired_differences(rows)
    comparisons = _classic_comparisons(rows, aggregates)
    decisions = _decisions(document, pairs, comparisons)
    return BatchAnalysisSummary(
        batch_id=state.batch_id,
        batch_config_hash=document.config_hash,
        batch_config=document.config.model_dump(mode="json"),
        rows=rows,
        aggregates=aggregates,
        paired_differences=pairs,
        classic_comparisons=comparisons,
        discovery_decisions=decisions,
        failed_runs=tuple(
            record for record in state.runs if record.status == "failed"
        ),
    )


def _plot_spec(
    summary: BatchAnalysisSummary,
    spec: str,
    output_path: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(8.5, 5.0))
    for agent, color, display in (
        ("gp", "#1565c0", "GP"),
        ("random", "#ef6c00", "Random"),
    ):
        rows = sorted(
            (row for row in summary.rows if row.spec == spec and row.agent == agent),
            key=lambda row: row.seed,
        )
        for row in rows:
            x = list(range(1, len(row.best_so_far) + 1))
            axis.plot(
                x,
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
                list(range(1, length + 1)),
                mean_curve,
                color=color,
                linewidth=2.6,
                label=f"{display} mean",
            )
    classic = next(
        row for row in summary.rows if row.spec == spec and row.agent == "classic"
    )
    axis.axhline(
        classic.best_score,
        color="#37474f",
        linestyle="--",
        linewidth=1.8,
        label="Classic",
    )
    axis.set_title(f"{spec}: best score so far")
    axis.set_xlabel("Evaluation number")
    axis.set_ylabel("Best composite score so far")
    axis.grid(alpha=0.2)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_path, dpi=160)
    plt.close(figure)


def _report(summary: BatchAnalysisSummary) -> str:
    config = summary.batch_config
    seeds = config["seeds"]
    lines = [
        f"# Batch {summary.batch_id}: GP vs random",
        "",
        "## Scope and evidence limits",
        "",
        (
            f"This batch reports descriptive statistics across n={len(seeds)} matched "
            "seeds. It does not perform or claim statistical significance."
        ),
        (
            "All Day 2 runs use openEMS subprocess physics. Cross-solver verification "
            "is pending for every spec, so no result is labeled a positive discovery."
        ),
        (
            f"The frozen batch config hash is `{summary.batch_config_hash}`; "
            f"budget={config['budget']}, seeds={seeds}, proposal space="
            f"`{config['proposal_space']['version']}`."
        ),
        (
            "wifi24 retains the Day 1 spec field-for-field. Its Day 2 run config hashes "
            f"differ from Day 1 `{DAY1_WIFI24_CONFIG_HASH}` because the proposal-space "
            "version and boundaries are now included, and the budgets/seeds differ."
        ),
        "",
        "## Per-seed traceable results",
        "",
        "| Spec | Seed | GP best | Random best | GP-Random | GP source | Random source |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for pair in summary.paired_differences:
        lines.append(
            f"| {pair.spec} | {pair.seed} | {pair.gp_best_score:.6f} | "
            f"{pair.random_best_score:.6f} | {pair.difference:+.6f} | "
            f"`{pair.gp_source_run_id}` | `{pair.random_source_run_id}` |"
        )
    lines.extend(
        [
            "",
            "## Descriptive aggregates",
            "",
            "| Spec | Agent | Mean best +/- sample SD | Relative to classic | Sources |",
            "|---|---|---:|---:|---|",
        ]
    )
    comparisons = {
        (item.spec, item.agent): item for item in summary.classic_comparisons
    }
    for aggregate in summary.aggregates:
        comparison = comparisons[(aggregate.spec, aggregate.agent)]
        sources = ", ".join(f"`{item}`" for item in aggregate.source_run_ids)
        lines.append(
            f"| {aggregate.spec} | {aggregate.agent} | "
            f"{aggregate.mean_best_score:.6f} ± "
            f"{aggregate.sample_std_best_score:.6f} | "
            f"{comparison.improvement_fraction:+.2%} | {sources}; classic "
            f"`{comparison.classic_source_run_id}` |"
        )
    lines.extend(
        [
            "",
            "## Discovery-policy assessment",
            "",
            "| Spec | GP >= classic threshold | Matched outcomes | Cross-solver | Verdict |",
            "|---|---|---|---|---|",
        ]
    )
    for decision in summary.discovery_decisions:
        threshold = "yes" if decision.improvement_threshold_met else "no"
        outcomes = (
            f"GP {decision.gp_wins}, random {decision.random_wins}, "
            f"ties {decision.ties}"
        )
        lines.append(
            f"| {decision.spec} | {threshold} "
            f"({decision.gp_vs_classic_improvement_fraction:+.2%}, threshold "
            f"{decision.improvement_threshold:.0%}) | {outcomes} | pending | "
            f"{decision.verdict} |"
        )
    lines.extend(["", "### Interpretation", ""])
    for decision in summary.discovery_decisions:
        lines.append(f"- **{decision.spec}:** {decision.reason}")
    lines.extend(["", "## Best-so-far curves", ""])
    for spec in config["specs"]:
        lines.append(f"![{spec} best-so-far]({spec}-best-so-far.png)")
        lines.append("")
    if summary.failed_runs:
        lines.extend(["## Failed runs", ""])
        for record in summary.failed_runs:
            lines.append(f"- `{record.run_id}`: {record.error}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def analyze_batch(batch_id: str, *, repo_root: Path) -> BatchAnalysisSummary:
    """Read one batch, generate JSON/Markdown/PNG artifacts, and return its summary."""

    batch_directory = repo_root / "runs" / f"batch_{batch_id}"
    state = load_batch_state(batch_directory / "state.json")
    document = load_batch_config(batch_directory / "config.json")
    summary = build_analysis(state, document, runs_root=repo_root / "runs")
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
    for spec in document.config.specs:
        _plot_spec(summary, spec, output / f"{spec}-best-so-far.png")
    return summary
