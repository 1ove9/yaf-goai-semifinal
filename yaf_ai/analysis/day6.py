"""Source-addressed analysis and figures for the Day 6 experiment."""

from __future__ import annotations

import json
import os
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import matplotlib
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from yaf_ai.analysis.chu import (
    QFitResult,
    electrical_size,
    fit_rlc_q,
    mclean_q_min,
    minimum_enclosing_sphere,
)
from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve
from yaf_ai.exploration.day6 import DAY6_BATCH_ID, Day6BatchConfigDocument
from yaf_ai.exploration.day6_cross_check import (
    Day6CrossCheckRunSummary,
    Day6SelectionDocument,
    band_validity,
    load_day6_selection,
    reconstruct_day6_design,
)
from yaf_ai.exploration.freeform_wire import HIGH_BAND_HZ, LOW_BAND_HZ
from yaf_ai.exploration.logger import AuditStepRecord
from yaf_core.domain.geometry import Geometry


class Day6BatchRow(BaseModel):
    """One source-addressed seed winner."""

    model_config = ConfigDict(frozen=True)

    agent: Literal["gp", "random"]
    seed: int
    source_run_id: str
    source_step_index: int = Field(ge=0)
    duration_seconds: float = Field(ge=0.0)
    score: float
    band_24_min_s11_db: float
    band_24_frequency_hz: float = Field(gt=0.0)
    band_58_min_s11_db: float
    band_58_frequency_hz: float = Field(gt=0.0)
    geometry_hash: str


class Day6AgentAggregate(BaseModel):
    """Descriptive statistics over five preregistered seeds."""

    model_config = ConfigDict(frozen=True)

    agent: Literal["gp", "random"]
    source_run_ids: tuple[str, ...]
    mean_best_score: float
    sample_standard_deviation: float = Field(ge=0.0)


class Day6PairDifference(BaseModel):
    """Matched GP-minus-random best-score difference for one seed."""

    model_config = ConfigDict(frozen=True)

    seed: int
    gp_source_run_id: str
    random_source_run_id: str
    gp_score: float
    random_score: float
    difference: float


class Day6ChuRow(BaseModel):
    """Descriptive Chu coordinate for one candidate band and solver."""

    model_config = ConfigDict(frozen=True)

    candidate_rank: int = Field(gt=0)
    solver: Literal["nec2", "openems"]
    band: Literal["2.4_GHz", "5.8_GHz"]
    source_run_id: str
    source_geometry_hash: str
    enclosing_radius_m: float = Field(gt=0.0)
    fit: QFitResult | None = None
    fit_error: str | None = None
    ka: float | None = Field(default=None, gt=0.0)
    q_min: float | None = Field(default=None, gt=0.0)
    q_over_q_min: float | None = Field(default=None, gt=0.0)
    included_in_plot: bool = False


class Day6GeometryDescription(BaseModel):
    """Source-derived shape descriptors without novelty claims."""

    model_config = ConfigDict(frozen=True)

    candidate_rank: int = Field(gt=0)
    source_run_id: str
    source_geometry_hash: str
    total_wire_length_m: float = Field(gt=0.0)
    enclosing_sphere_radius_m: float = Field(gt=0.0)
    planarity_rms_residual_m: float = Field(ge=0.0)
    planarity_residual_over_radius: float = Field(ge=0.0)


class Day6CrossCheckDiagnostic(BaseModel):
    """Quantitative flat-curve diagnostic without claiming a proven root cause."""

    model_config = ConfigDict(frozen=True)

    candidate_rank: int = Field(gt=0)
    source_run_id: str
    nec2_peak_to_peak_s11_db: float = Field(ge=0.0)
    openems_peak_to_peak_s11_db: float = Field(ge=0.0)
    openems_numerically_flat_threshold_db: float = 1e-6
    openems_near_flat_threshold_db: float = 0.05
    openems_numerically_flat: bool
    openems_near_flat: bool
    classification: Literal[
        "link_or_geometry_coupling_anomaly",
        "unresolved_solver_disagreement",
    ]


def classify_day6_curve_spans(
    nec2_span_db: float, openems_span_db: float
) -> Literal[
    "link_or_geometry_coupling_anomaly",
    "unresolved_solver_disagreement",
]:
    """Classify a large-notch/near-flat contrast without asserting a root cause."""

    if openems_span_db <= 0.05 and nec2_span_db > 1.0:
        return "link_or_geometry_coupling_anomaly"
    return "unresolved_solver_disagreement"


class Day6ConvergenceLevel(BaseModel):
    """One source-addressed openEMS mesh level from convergence.json."""

    model_config = ConfigDict(frozen=True)

    refinement: float = Field(gt=0.0)
    run_id: str
    high_band_shift_from_previous: float | None = Field(default=None, ge=0.0)
    curve: SolverCurve


class Day6ConvergenceSummary(BaseModel):
    """Frozen high-band self-convergence decision for the openEMS instrument."""

    model_config = ConfigDict(frozen=True)

    protocol: str
    threshold: float = Field(ge=0.0)
    levels: tuple[Day6ConvergenceLevel, ...]
    selected_refinement: float | None = Field(default=None, gt=0.0)
    status: Literal[
        "converged",
        "infeasible_at_current_compute",
        "self_convergence_not_established",
    ]
    raw_execution_status: str | None = None
    assessment_reason: str | None = None


class Day6AnalysisSummary(BaseModel):
    """Complete machine-readable Day 6 result table."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str = DAY6_BATCH_ID
    config_hash: str
    ocfd_source_run_id: str
    ocfd_score: float
    straight_source_run_id: str
    straight_score: float
    rows: tuple[Day6BatchRow, ...]
    aggregates: tuple[Day6AgentAggregate, ...]
    paired_differences: tuple[Day6PairDifference, ...]
    selection: Day6SelectionDocument
    convergence: Day6ConvergenceSummary
    cross_checks: tuple[Day6CrossCheckRunSummary, ...]
    cross_check_diagnostics: tuple[Day6CrossCheckDiagnostic, ...]
    geometry: tuple[Day6GeometryDescription, ...]
    chu: tuple[Day6ChuRow, ...]
    final_verdict: Literal["confirmed_improvement", "insufficient_evidence"]


def _load_config(repo_root: Path) -> Day6BatchConfigDocument:
    try:
        return Day6BatchConfigDocument.model_validate_json(
            (
                repo_root
                / "artifacts"
                / "analysis"
                / "day6-freeform"
                / "batch-config.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load Day 6 analysis config: {error}") from error


def _load_evaluations(path: Path) -> tuple[AuditStepRecord, ...]:
    records: list[AuditStepRecord] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            if raw.get("event_type") == "evaluation":
                records.append(AuditStepRecord.model_validate(raw))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CrossCheckError(f"cannot load batch evidence {path}: {error}") from error
    if not records:
        raise CrossCheckError(f"batch evidence has no evaluations: {path}")
    return tuple(records)


def _best(records: Sequence[AuditStepRecord]) -> AuditStepRecord:
    return min(records, key=lambda row: (-row.score, row.step_index))


def _batch_rows(
    repo_root: Path, config: Day6BatchConfigDocument
) -> tuple[tuple[Day6BatchRow, ...], dict[str, tuple[AuditStepRecord, ...]]]:
    try:
        state = json.loads(
            (
                repo_root
                / "artifacts"
                / "analysis"
                / "day6-freeform"
                / "batch-state.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot load archived Day 6 batch state: {error}") from error
    durations = {
        str(record["run_id"]): float(record["duration_seconds"])
        for record in state.get("runs", [])
        if record.get("status") == "completed"
    }
    rows: list[Day6BatchRow] = []
    logs: dict[str, tuple[AuditStepRecord, ...]] = {}
    for agent in config.config.agents:
        for seed in config.config.seeds:
            run_id = f"day6-freeform-dual-{agent}-s{seed}"
            records = _load_evaluations(
                repo_root / "artifacts" / "runs" / run_id / "log.jsonl"
            )
            if len(records) != config.config.budget:
                raise CrossCheckError(
                    f"{run_id} has {len(records)} evaluations, expected {config.config.budget}"
                )
            if any(record.solver_mode != "subprocess" for record in records):
                raise CrossCheckError(f"{run_id} contains a non-subprocess result")
            if run_id not in durations:
                raise CrossCheckError(f"{run_id} has no completed duration record")
            best = _best(records)
            logs[run_id] = records
            rows.append(
                Day6BatchRow(
                    agent=agent,
                    seed=seed,
                    source_run_id=run_id,
                    source_step_index=best.step_index,
                    duration_seconds=durations[run_id],
                    score=best.score,
                    band_24_min_s11_db=best.metrics["band_24_min_s11_db"],
                    band_24_frequency_hz=best.metrics["band_24_frequency_hz"],
                    band_58_min_s11_db=best.metrics["band_58_min_s11_db"],
                    band_58_frequency_hz=best.metrics["band_58_frequency_hz"],
                    geometry_hash=best.geometry_hash,
                )
            )
    return tuple(rows), logs


def _aggregates(rows: Sequence[Day6BatchRow]) -> tuple[Day6AgentAggregate, ...]:
    output: list[Day6AgentAggregate] = []
    for agent in ("gp", "random"):
        selected = [row for row in rows if row.agent == agent]
        scores = [row.score for row in selected]
        output.append(
            Day6AgentAggregate(
                agent=agent,
                source_run_ids=tuple(row.source_run_id for row in selected),
                mean_best_score=statistics.fmean(scores),
                sample_standard_deviation=statistics.stdev(scores),
            )
        )
    return tuple(output)


def _pairs(rows: Sequence[Day6BatchRow]) -> tuple[Day6PairDifference, ...]:
    by_address = {(row.agent, row.seed): row for row in rows}
    return tuple(
        Day6PairDifference(
            seed=seed,
            gp_source_run_id=by_address[("gp", seed)].source_run_id,
            random_source_run_id=by_address[("random", seed)].source_run_id,
            gp_score=by_address[("gp", seed)].score,
            random_score=by_address[("random", seed)].score,
            difference=(
                by_address[("gp", seed)].score
                - by_address[("random", seed)].score
            ),
        )
        for seed in sorted({row.seed for row in rows})
    )


def _planarity(points: Sequence[Sequence[float]]) -> float:
    array = np.asarray(points, dtype=np.float64)
    centered = array - np.mean(array, axis=0)
    _left, _values, right = np.linalg.svd(centered, full_matrices=False)
    distances = centered @ right[-1]
    return float(np.sqrt(np.mean(np.square(distances))))


def _centerline_sphere_points(geometry: Geometry) -> tuple[tuple[float, ...], ...]:
    """Return exact control vertices; collinear subdivision points cannot expand a sphere."""

    positive = geometry.metadata.get("control_positive")
    negative = geometry.metadata.get("control_negative")
    if not isinstance(positive, list) or not isinstance(negative, list):
        raise CrossCheckError("Day 6 geometry is missing control-centerline vertices")
    return tuple(
        tuple(float(coordinate) for coordinate in point)
        for point in [*positive, *negative]
    )


def _geometry_rows(
    repo_root: Path, selection: Day6SelectionDocument
) -> tuple[Day6GeometryDescription, ...]:
    rows: list[Day6GeometryDescription] = []
    for candidate in selection.candidates:
        geometry, _seed = reconstruct_day6_design(repo_root, candidate)
        sphere_points = _centerline_sphere_points(geometry)
        sphere = minimum_enclosing_sphere(sphere_points)
        residual = _planarity(geometry.vertices)
        rows.append(
            Day6GeometryDescription(
                candidate_rank=candidate.rank,
                source_run_id=candidate.source_run_id,
                source_geometry_hash=candidate.source_geometry_hash,
                total_wire_length_m=float(geometry.metadata["total_wire_length_m"]),
                enclosing_sphere_radius_m=sphere.radius_m,
                planarity_rms_residual_m=residual,
                planarity_residual_over_radius=residual / sphere.radius_m,
            )
        )
    return tuple(rows)


def _fit_band(
    curve: SolverCurve,
    band: Literal["2.4_GHz", "5.8_GHz"],
) -> QFitResult:
    target = LOW_BAND_HZ if band == "2.4_GHz" else HIGH_BAND_HZ
    padding = 0.50e9 if band == "2.4_GHz" else 0.60e9
    frequencies: list[float] = []
    values: list[float] = []
    for frequency, value in zip(curve.frequency_hz, curve.s11_db, strict=True):
        if target[0] - padding <= frequency <= target[1] + padding:
            frequencies.append(frequency)
            values.append(value)
    fit = fit_rlc_q(frequencies, values)
    if not target[0] <= fit.fitted_resonance_hz <= target[1]:
        raise ValueError("fitted resonance left the target band")
    return fit


def _chu_rows(
    repo_root: Path,
    summaries: Sequence[Day6CrossCheckRunSummary],
) -> tuple[Day6ChuRow, ...]:
    rows: list[Day6ChuRow] = []
    for summary in summaries:
        geometry, _seed = reconstruct_day6_design(repo_root, summary.selected_design)
        radius = minimum_enclosing_sphere(
            _centerline_sphere_points(geometry)
        ).radius_m
        for solver, curve in (("nec2", summary.nec2), ("openems", summary.openems)):
            for band in ("2.4_GHz", "5.8_GHz"):
                try:
                    fit = _fit_band(curve, band)
                except ValueError as error:
                    rows.append(
                        Day6ChuRow(
                            candidate_rank=summary.selected_design.rank,
                            solver=solver,
                            band=band,
                            source_run_id=summary.run_id,
                            source_geometry_hash=summary.selected_design.source_geometry_hash,
                            enclosing_radius_m=radius,
                            fit_error=str(error),
                        )
                    )
                    continue
                ka = electrical_size(fit.fitted_resonance_hz, radius)
                q_min = mclean_q_min(ka)
                ratio = fit.q_loaded / q_min
                rows.append(
                    Day6ChuRow(
                        candidate_rank=summary.selected_design.rank,
                        solver=solver,
                        band=band,
                        source_run_id=summary.run_id,
                        source_geometry_hash=summary.selected_design.source_geometry_hash,
                        enclosing_radius_m=radius,
                        fit=fit,
                        ka=ka,
                        q_min=q_min,
                        q_over_q_min=ratio,
                        included_in_plot=(
                            fit.confidence == "high_confidence" and ratio >= 1.0
                        ),
                    )
                )
    return tuple(rows)


def _load_cross_checks(repo_root: Path) -> tuple[Day6CrossCheckRunSummary, ...]:
    summaries: list[Day6CrossCheckRunSummary] = []
    for rank in (1, 2):
        run_id = f"day6-freeform-final-crosscheck-top{rank}"
        try:
            summaries.append(
                Day6CrossCheckRunSummary.model_validate_json(
                    (
                        repo_root / "artifacts" / "runs" / run_id / "summary.json"
                    ).read_text(encoding="utf-8")
                )
            )
        except (OSError, ValidationError) as error:
            raise CrossCheckError(f"cannot load final cross-check {run_id}: {error}") from error
    return tuple(summaries)


def _cross_check_diagnostics(
    summaries: Sequence[Day6CrossCheckRunSummary],
) -> tuple[Day6CrossCheckDiagnostic, ...]:
    rows: list[Day6CrossCheckDiagnostic] = []
    for summary in summaries:
        nec2_span = max(summary.nec2.s11_db) - min(summary.nec2.s11_db)
        openems_span = max(summary.openems.s11_db) - min(summary.openems.s11_db)
        numerically_flat = openems_span <= 1e-6
        near_flat = openems_span <= 0.05
        rows.append(
            Day6CrossCheckDiagnostic(
                candidate_rank=summary.selected_design.rank,
                source_run_id=summary.run_id,
                nec2_peak_to_peak_s11_db=nec2_span,
                openems_peak_to_peak_s11_db=openems_span,
                openems_numerically_flat=numerically_flat,
                openems_near_flat=near_flat,
                classification=classify_day6_curve_spans(nec2_span, openems_span),
            )
        )
    return tuple(rows)


def _load_convergence(repo_root: Path) -> Day6ConvergenceSummary:
    try:
        raw = Day6ConvergenceSummary.model_validate_json(
            (
                repo_root
                / "artifacts"
                / "analysis"
                / "day6-freeform"
                / "convergence.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load Day 6 convergence evidence: {error}") from error
    if any(
        not band_validity(level.curve, HIGH_BAND_HZ).valid
        for level in raw.levels
    ):
        return raw.model_copy(
            update={
                "selected_refinement": None,
                "status": "self_convergence_not_established",
                "raw_execution_status": raw.status,
                "assessment_reason": (
                    "At least one adjacent mesh curve has no v2.1-valid 5.8 GHz "
                    "resonance (local interior minimum deeper than or equal to -6 dB); "
                    "the shallow-minimum position shift is descriptive only."
                ),
            }
        )
    return raw


def build_day6_analysis(
    repo_root: Path,
) -> tuple[Day6AnalysisSummary, dict[str, tuple[AuditStepRecord, ...]]]:
    """Build the analysis only from committed/archive-ready evidence bytes."""

    config = _load_config(repo_root)
    rows, logs = _batch_rows(repo_root, config)
    selection = load_day6_selection(repo_root)
    checks = _load_cross_checks(repo_root)
    summary = Day6AnalysisSummary(
        config_hash=config.config_hash,
        ocfd_source_run_id=config.config.ocfd_run_id,
        ocfd_score=config.config.ocfd_score,
        straight_source_run_id=config.config.straight_run_id,
        straight_score=config.config.straight_score,
        rows=rows,
        aggregates=_aggregates(rows),
        paired_differences=_pairs(rows),
        selection=selection,
        convergence=_load_convergence(repo_root),
        cross_checks=checks,
        cross_check_diagnostics=_cross_check_diagnostics(checks),
        geometry=_geometry_rows(repo_root, selection),
        chu=_chu_rows(repo_root, checks),
        final_verdict=(
            "confirmed_improvement"
            if any(check.discovery_verdict == "confirmed_improvement" for check in checks)
            else "insufficient_evidence"
        ),
    )
    return summary, logs


def _write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _plot_best_so_far(
    output: Path,
    logs: dict[str, tuple[AuditStepRecord, ...]],
    summary: Day6AnalysisSummary,
) -> None:
    figure, axis = plt.subplots(figsize=(9.0, 5.5))
    colors = {"gp": "#1769aa", "random": "#d97706"}
    for agent in ("gp", "random"):
        trajectories: list[np.ndarray[Any, np.dtype[np.float64]]] = []
        for row in summary.rows:
            if row.agent != agent:
                continue
            values = np.maximum.accumulate(
                np.asarray([record.score for record in logs[row.source_run_id]])
            )
            trajectories.append(values)
            axis.plot(
                np.arange(1, len(values) + 1),
                values,
                color=colors[agent],
                alpha=0.22,
                linewidth=1.0,
            )
        mean = np.mean(np.vstack(trajectories), axis=0)
        axis.plot(
            np.arange(1, len(mean) + 1),
            mean,
            color=colors[agent],
            linewidth=2.8,
            label=f"{agent.upper()} mean",
        )
    axis.axhline(summary.ocfd_score, color="black", linestyle="--", label="OCFD optimum")
    axis.set_xlabel("Accepted evaluation")
    axis.set_ylabel("Best-so-far worst-band score")
    axis.set_title("Day 6 free-form dual-band exploration")
    axis.grid(alpha=0.2)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output / "best-so-far.png", dpi=180)
    plt.close(figure)


def _plot_geometry(repo_root: Path, output: Path, selection: Day6SelectionDocument) -> None:
    figure = plt.figure(figsize=(14.0, 9.0))
    for row, candidate in enumerate(selection.candidates):
        geometry, _seed = reconstruct_day6_design(repo_root, candidate)
        title_suffix = (
            f"{candidate.source_run_id} step {candidate.source_step_index}"
        )
        iso = figure.add_subplot(2, 3, row * 3 + 1, projection="3d")
        xy = figure.add_subplot(2, 3, row * 3 + 2)
        xz = figure.add_subplot(2, 3, row * 3 + 3)
        for start_index, stop_index in geometry.faces[1:]:
            start = geometry.vertices[start_index]
            stop = geometry.vertices[stop_index]
            iso.plot(
                [start[0] * 1e3, stop[0] * 1e3],
                [start[1] * 1e3, stop[1] * 1e3],
                [start[2] * 1e3, stop[2] * 1e3],
                color="#1769aa",
                linewidth=1.7,
            )
            xy.plot(
                [start[0] * 1e3, stop[0] * 1e3],
                [start[1] * 1e3, stop[1] * 1e3],
                color="#1769aa",
                linewidth=1.7,
            )
            xz.plot(
                [start[0] * 1e3, stop[0] * 1e3],
                [start[2] * 1e3, stop[2] * 1e3],
                color="#1769aa",
                linewidth=1.7,
            )
        iso.set(xlabel="x (mm)", ylabel="y (mm)", zlabel="z (mm)")
        iso.set_xlim(-20, 20)
        iso.set_ylim(-20, 20)
        iso.set_zlim(-20, 20)
        iso.view_init(elev=25.0, azim=-60.0)
        iso.set_title(f"Top {candidate.rank} isometric\n{title_suffix}")
        for axis, vertical, label in ((xy, "y (mm)", "xy/top"), (xz, "z (mm)", "xz/side")):
            axis.set_xlim(-20, 20)
            axis.set_ylim(-20, 20)
            axis.set_aspect("equal", adjustable="box")
            axis.set_xlabel("x (mm)")
            axis.set_ylabel(vertical)
            axis.grid(alpha=0.25)
            axis.set_title(f"Top {candidate.rank} {label}\n{title_suffix}")
    figure.suptitle(
        "Three-view native symmetric free-form centerlines (same geometry in both solvers)"
    )
    figure.tight_layout()
    figure.savefig(output / "top-geometries-3d.png", dpi=180)
    plt.close(figure)


def _plot_cross_checks(output: Path, checks: Sequence[Day6CrossCheckRunSummary]) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(10.0, 8.0), sharex=True)
    for axis, summary in zip(axes, checks, strict=True):
        for label, curve, color in (
            ("NEC2 lambda/160", summary.nec2, "#1769aa"),
            ("openEMS converged mesh", summary.openems, "#d97706"),
        ):
            axis.plot(
                np.asarray(curve.frequency_hz) / 1e9,
                curve.s11_db,
                label=label,
                color=color,
                linewidth=1.7,
            )
        axis.axvspan(2.40, 2.50, color="#60a5fa", alpha=0.18)
        axis.axvspan(5.725, 5.875, color="#f59e0b", alpha=0.18)
        axis.axhline(-6.0, color="black", linestyle=":", linewidth=1.0)
        axis.set_ylabel("S11 (dB)")
        axis.set_title(
            f"Top {summary.selected_design.rank}: {summary.decision.verdict}; "
            f"Pearson={summary.decision.whole_sweep_pearson}"
        )
        axis.grid(alpha=0.2)
        axis.legend(loc="best")
    axes[-1].set_xlabel("Frequency (GHz)")
    figure.tight_layout()
    figure.savefig(output / "dual-solver-s11.png", dpi=180)
    plt.close(figure)


def _plot_chu(output: Path, rows: Sequence[Day6ChuRow]) -> None:
    figure, axis = plt.subplots(figsize=(8.0, 5.5))
    markers = {"2.4_GHz": "o", "5.8_GHz": "s"}
    colors = {"nec2": "#1769aa", "openems": "#d97706"}
    for row in rows:
        if not row.included_in_plot or row.ka is None or row.q_over_q_min is None:
            continue
        axis.scatter(
            row.ka,
            row.q_over_q_min,
            marker=markers[row.band],
            color=colors[row.solver],
            s=70,
            label=f"top{row.candidate_rank} {row.solver} {row.band}",
        )
    axis.axhline(1.0, color="black", linestyle="--", label="Chu-McLean lower bound")
    axis.set_yscale("log")
    axis.set_xlabel("Electrical size ka")
    axis.set_ylabel("Loaded-Q proxy / Q_min")
    axis.set_title("Descriptive dual-resonance Chu coordinates")
    axis.grid(alpha=0.2, which="both")
    axis.legend(fontsize=7, ncol=2)
    figure.tight_layout()
    figure.savefig(output / "day6-chu.png", dpi=180)
    plt.close(figure)


def _report(summary: Day6AnalysisSummary) -> str:
    lines = [
        "# Day 6 free-form 3D wire dual-band result",
        "",
        f"Final verdict: `{summary.final_verdict}`.",
        "",
        "## Frozen references and batch",
        "",
        f"OCFD `{summary.ocfd_source_run_id}` score: {summary.ocfd_score:.9f}. "
        f"Straight control `{summary.straight_source_run_id}` score: {summary.straight_score:.9f}.",
        "",
        "| agent | seed | best score | 2.4 GHz S11 | 5.8 GHz S11 | elapsed | source |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary.rows:
        lines.append(
            f"| {row.agent} | {row.seed} | {row.score:.9f} | "
            f"{row.band_24_min_s11_db:.6f} dB | {row.band_58_min_s11_db:.6f} dB | "
            f"{row.duration_seconds:.3f} s | "
            f"`{row.source_run_id}` step {row.source_step_index} |"
        )
    lines.extend(["", "Descriptive aggregate only (n=5; no significance claim):", ""])
    for aggregate in summary.aggregates:
        lines.append(
            f"- {aggregate.agent}: {aggregate.mean_best_score:.9f} +/- "
            f"{aggregate.sample_standard_deviation:.9f} sample SD."
        )
    lines.extend(["", "Paired GP-minus-random differences: " + ", ".join(
        f"seed {row.seed}: {row.difference:+.9f}" for row in summary.paired_differences
    ) + ".", "", "## openEMS 5.8 GHz self-convergence", "", "| refinement | f_min | S11 | elapsed | shift | source |", "|---:|---:|---:|---:|---:|---|"])
    for level in summary.convergence.levels:
        validity_indices = [
            index
            for index, frequency in enumerate(level.curve.frequency_hz)
            if HIGH_BAND_HZ[0] <= frequency <= HIGH_BAND_HZ[1]
        ]
        minimum_index = min(validity_indices, key=level.curve.s11_db.__getitem__)
        lines.append(
            f"| {level.refinement:g}x | {level.curve.frequency_hz[minimum_index] / 1e9:.3f} GHz | "
            f"{level.curve.s11_db[minimum_index]:.6f} dB | "
            f"{level.curve.simulation_time_seconds:.3f} s | "
            f"{level.high_band_shift_from_previous} | `{level.run_id}` |"
        )
    lines.extend(
        [
            "",
            f"Instrument status: `{summary.convergence.status}`; frozen refinement "
            f"{summary.convergence.selected_refinement} at the unchanged "
            f"{summary.convergence.threshold:.1%} adjacent-shift threshold. "
            f"{summary.convergence.assessment_reason or ''}",
            "The completed top-2 curves are retained as diagnostic evidence. Because "
            "self-convergence was not established and both final openEMS curves also "
            "fail the -6 dB resonance gate, they cannot support confirmation.",
            "",
            "## Frozen candidates and cross-solver decisions",
            "",
        ]
    )
    for check in summary.cross_checks:
        low = check.decision.low_band
        high = check.decision.high_band
        lines.extend(
            [
                f"### Candidate top {check.selected_design.rank}",
                "",
                f"Source `{check.selected_design.source_run_id}` step "
                f"{check.selected_design.source_step_index}, score "
                f"{check.selected_design.source_score:.9f}; reference gate "
                f"{check.reference_gate_met}. Cross-check `{check.run_id}`: "
                f"`{check.decision.verdict}`; discovery `{check.discovery_verdict}`.",
                "",
                f"- 2.4 GHz: NEC2 {low.nec2.minimum_frequency_hz / 1e9:.3f} GHz/"
                f"{low.nec2.minimum_s11_db:.6f} dB; openEMS "
                f"{low.openems.minimum_frequency_hz / 1e9:.3f} GHz/"
                f"{low.openems.minimum_s11_db:.6f} dB; gap "
                f"{low.resonance_relative_difference}.",
                f"- 5.8 GHz: NEC2 {high.nec2.minimum_frequency_hz / 1e9:.3f} GHz/"
                f"{high.nec2.minimum_s11_db:.6f} dB; openEMS "
                f"{high.openems.minimum_frequency_hz / 1e9:.3f} GHz/"
                f"{high.openems.minimum_s11_db:.6f} dB; gap "
                f"{high.resonance_relative_difference}.",
                f"- Whole-sweep Pearson: {check.decision.whole_sweep_pearson}.",
                "",
            ]
        )
    lines.extend(["## Cross-check anomaly attribution", ""])
    for diagnostic in summary.cross_check_diagnostics:
        lines.append(
            f"- Top {diagnostic.candidate_rank} `{diagnostic.source_run_id}`: NEC2 "
            f"peak-to-peak S11 span {diagnostic.nec2_peak_to_peak_s11_db:.9f} dB; "
            f"openEMS span {diagnostic.openems_peak_to_peak_s11_db:.12g} dB "
            f"(numerically-flat threshold "
            f"{diagnostic.openems_numerically_flat_threshold_db:g} dB; "
            f"near-flat diagnostic threshold "
            f"{diagnostic.openems_near_flat_threshold_db:g} dB; "
            f"numerically flat={diagnostic.openems_numerically_flat}; "
            f"near flat={diagnostic.openems_near_flat}). "
            f"Classification: `{diagnostic.classification}`."
        )
    lines.extend(
        [
            "",
            "Both openEMS curves are physically near-flat while the source-matched NEC2 "
            "curves contain large notches. The emitted XML uses the installed CSXCAD "
            "finite-radius `Wire`/`Vertex` schema and unit tests verify point order, "
            "but this end-to-end result does not establish that the free-form conductor "
            "coupled to the lumped port in openEMS. The classification is therefore a "
            "model-chain anomaly, not evidence of a genuine physical disagreement. No "
            "additional design or solver retry was selected after seeing the result.",
            "",
        ]
    )
    lines.extend(
        [
            "## Geometry and Chu positioning",
            "",
            "The 3D residual is descriptive only; it is not evidence of novelty. Chu rows "
            "reuse the pre-registered loaded-Q proxy independently around both target "
            "resonances. Low-confidence or ineligible fits remain in `summary.json` and "
            "are omitted from the Chu plot.",
            "",
        ]
    )
    for geometry_row in summary.geometry:
        lines.append(
            f"- Top {geometry_row.candidate_rank} (`{geometry_row.source_run_id}`): length "
            f"{geometry_row.total_wire_length_m * 1e3:.6f} mm; enclosing radius "
            f"{geometry_row.enclosing_sphere_radius_m * 1e3:.6f} mm; planarity RMS "
            f"{geometry_row.planarity_rms_residual_m * 1e3:.6f} mm "
            f"({geometry_row.planarity_residual_over_radius:.6f} of radius)."
        )
    lines.extend(
        [
            "",
            "![Best-so-far](best-so-far.png)",
            "",
            "![Top free-form geometries](top-geometries-3d.png)",
            "",
            "![Dual-solver S11](dual-solver-s11.png)",
            "",
            "![Day 6 Chu coordinates](day6-chu.png)",
            "",
        ]
    )
    return "\n".join(lines)


def write_day6_analysis(repo_root: Path) -> Day6AnalysisSummary:
    """Write the JSON, report, and four source-backed figures."""

    summary, logs = build_day6_analysis(repo_root)
    output = repo_root / "artifacts" / "analysis" / "day6-freeform"
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "summary.json", summary.model_dump(mode="json"))
    _write_json(
        output / "convergence-assessment.json",
        summary.convergence.model_dump(mode="json"),
    )
    (output / "report.md").write_bytes((_report(summary) + "\n").encode("utf-8"))
    _plot_best_so_far(output, logs, summary)
    _plot_geometry(repo_root, output, summary.selection)
    _plot_cross_checks(output, summary.cross_checks)
    _plot_chu(output, summary.chu)
    return summary
