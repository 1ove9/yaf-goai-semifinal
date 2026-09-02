"""Execute the frozen final patch instrument-convergence ladder."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

import psutil
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.cross_check import (
    AirVariantDefinition,
    CrossCheckError,
    CrossCheckRunSummary,
    SolverCurve,
    WireGridDefinition,
    _curve,
    build_air_variant,
    reconstruct_archived_design,
)
from yaf_ai.exploration.cross_check_v2 import (
    ConvergencePoint,
    ConvergenceRunSummary,
    _canonical_hash,
    _load_anchor_gate,
    _run_nec2_grid,
    build_wire_grid,
)
from yaf_ai.exploration.patch_final_protocol import (
    FREQUENCY_POINTS,
    FREQUENCY_RANGE_HZ,
    MAX_SINGLE_RUN_SECONDS,
    OPENEMS_REFINEMENT_LADDER,
    SOURCE_CONVERGENCE_RUN_ID,
    SOURCE_CROSSCHECK_RUN_ID,
    SOURCE_DESIGN_INDEX,
    SOURCE_GEOMETRY_HASH,
    SOURCE_RUN_ID,
    SOURCE_STEP_INDEX,
    GridResourcePrediction,
    grid_estimate_for_pearson,
    power_law_grid_estimate,
    predict_grid_resources,
    predict_openems_runtime_seconds,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

ANALYSIS_ID = "day5-patch-final"
OPENEMS_SELF_CONVERGENCE_THRESHOLD = 0.03
OpenEMSAction = Literal["selected", "run_4x", "infeasible_at_current_compute"]
ModelT = TypeVar("ModelT", bound=BaseModel)


class GapExtrapolationSnapshot(BaseModel):
    """Power-law roadmap recomputed after one completed grid."""

    model_config = ConfigDict(frozen=True)

    after_grid_intervals: int = Field(gt=1)
    completed_grids: tuple[int, ...]
    completed_gaps: tuple[float, ...]
    estimated_grid_for_five_percent: int | None = Field(default=None, gt=0)
    estimated_grid_for_pearson: int | None = Field(default=None, gt=0)


class OpenEMSRefinementRunSummary(BaseModel):
    """Archive-compatible openEMS self-convergence stage."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 1
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int]
    source_run_id: str = SOURCE_RUN_ID
    source_geometry_hash: str = SOURCE_GEOMETRY_HASH
    air_variant: AirVariantDefinition
    refinement: float = Field(gt=0.0)
    baseline_refinement: float = Field(gt=0.0)
    predicted_seconds: float = Field(gt=0.0)
    actual_wall_seconds: float = Field(ge=0.0)
    baseline_curve: SolverCurve
    curve: SolverCurve
    adjacent_resonance_shift: float = Field(ge=0.0)
    action: OpenEMSAction


class NEC2GridRunSummary(BaseModel):
    """Archive-compatible resource-gated NEC2 grid stage."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 1
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int]
    source_run_id: str = SOURCE_RUN_ID
    source_geometry_hash: str = SOURCE_GEOMETRY_HASH
    resource_prediction: GridResourcePrediction
    grid_definition: WireGridDefinition
    point: ConvergencePoint
    actual_wall_seconds: float = Field(ge=0.0)
    extrapolation: GapExtrapolationSnapshot


class PatchResourceStop(BaseModel):
    """A preregistered stop made before launching an infeasible grid."""

    model_config = ConfigDict(frozen=True)

    target_grid_intervals: int = Field(gt=1)
    prediction: GridResourcePrediction
    verdict: Literal["infeasible_at_current_compute"] = (
        "infeasible_at_current_compute"
    )


class PatchConvergenceSeries(BaseModel):
    """Combined archived baseline and new instrument sequence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    analysis_id: str = ANALYSIS_ID
    candidate_source_run_id: str = SOURCE_RUN_ID
    candidate_design_index: int = SOURCE_DESIGN_INDEX
    candidate_step_index: int = SOURCE_STEP_INDEX
    candidate_geometry_hash: str = SOURCE_GEOMETRY_HASH
    frequency_range_hz: tuple[float, float] = FREQUENCY_RANGE_HZ
    frequency_points: int = FREQUENCY_POINTS
    openems_baseline_run_id: str = SOURCE_CROSSCHECK_RUN_ID
    nec2_baseline_run_id: str = SOURCE_CONVERGENCE_RUN_ID
    openems_runs: tuple[OpenEMSRefinementRunSummary, ...]
    nec2_runs: tuple[NEC2GridRunSummary, ...]
    selected_openems_refinement: float | None = Field(default=None, gt=0.0)
    selected_nec2_grid: int = Field(gt=1)
    resource_stop: PatchResourceStop | None = None


def _read_model(path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load patch convergence evidence {path}: {error}") from error


def _write_run(directory: Path, event: dict[str, Any], summary: BaseModel) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    line = json.dumps(
        event, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ) + "\n"
    (directory / "log.jsonl").write_bytes(line.encode("utf-8"))
    temporary = directory / "summary.json.tmp"
    temporary.write_bytes(
        (
            json.dumps(
                summary.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    os.replace(temporary, directory / "summary.json")


def _source(repo_root: Path) -> CrossCheckRunSummary:
    source = _read_model(
        repo_root
        / "artifacts"
        / "runs"
        / SOURCE_CROSSCHECK_RUN_ID
        / "summary.json",
        CrossCheckRunSummary,
    )
    if (
        source.source_run_id != SOURCE_RUN_ID
        or source.source_design_index != SOURCE_DESIGN_INDEX
        or source.source_geometry_hash != SOURCE_GEOMETRY_HASH
        or tuple(source.openems.frequency_hz)[0] != FREQUENCY_RANGE_HZ[0]
        or tuple(source.openems.frequency_hz)[-1] != FREQUENCY_RANGE_HZ[1]
        or len(source.openems.frequency_hz) != FREQUENCY_POINTS
    ):
        raise CrossCheckError("archived Day 3 patch source drifted from preregistration")
    return source


def _prior_convergence(repo_root: Path) -> ConvergenceRunSummary:
    return _read_model(
        repo_root
        / "artifacts"
        / "runs"
        / SOURCE_CONVERGENCE_RUN_ID
        / "summary.json",
        ConvergenceRunSummary,
    )


def _air_geometry(
    repo_root: Path, source: CrossCheckRunSummary
) -> tuple[Geometry, int]:
    archived, design, _config, geometry = reconstruct_archived_design(
        SOURCE_RUN_ID,
        SOURCE_DESIGN_INDEX,
        artifacts_root=repo_root / "artifacts" / "runs",
    )
    if design.step_index != SOURCE_STEP_INDEX or design.geometry_hash != SOURCE_GEOMETRY_HASH:
        raise CrossCheckError("frozen patch candidate address changed")
    air_geometry, definition = build_air_variant(geometry)
    if definition != source.air_variant:
        raise CrossCheckError("Day 3 air transformation no longer reproduces its archive")
    return air_geometry, archived.seed


def _relative_shift(first_hz: float, second_hz: float) -> float:
    if first_hz <= 0.0 or second_hz <= 0.0:
        raise ValueError("resonance frequencies must be positive")
    return abs(first_hz - second_hz) / second_hz


async def run_openems_refinement(
    repo_root: Path,
    *,
    source: CrossCheckRunSummary,
    baseline: SolverCurve,
    baseline_refinement: float,
    refinement: float,
    baseline_actual_seconds: float,
) -> OpenEMSRefinementRunSummary:
    """Run one exact-sweep openEMS refinement and persist it locally."""

    run_id = f"{ANALYSIS_ID}-openems-{refinement:g}x"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"openEMS patch run already exists: {run_id}")
    predicted = predict_openems_runtime_seconds(
        baseline_refinement=baseline_refinement,
        baseline_actual_seconds=baseline_actual_seconds,
        target_refinement=refinement,
    )
    if predicted > MAX_SINGLE_RUN_SECONDS:
        raise CrossCheckError(
            f"openEMS {refinement:g}x prediction {predicted:.3f}s exceeds 3 hours"
        )
    air_geometry, seed = _air_geometry(repo_root, source)
    spec = SimulationSpec(
        name=run_id,
        frequency_range=FREQUENCY_RANGE_HZ,
        frequency_points=FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings={"openems_mesh_refinement": refinement},
    )
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    adapter = OpenEMSAdapter()
    curve = _curve(await adapter.solve(await adapter.mesh(air_geometry, spec), spec))
    wall = time.perf_counter() - started
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"openEMS {refinement:g}x used {curve.solver_mode}")
    shift = _relative_shift(baseline.resonance_frequency_hz, curve.resonance_frequency_hz)
    action: OpenEMSAction = (
        "selected"
        if shift <= OPENEMS_SELF_CONVERGENCE_THRESHOLD
        else "run_4x"
        if refinement == OPENEMS_REFINEMENT_LADDER[0]
        else "infeasible_at_current_compute"
    )
    config = {
        "execution_note": "docs/patch-crosscheck-final-execution-note.md",
        "source_crosscheck_run_id": SOURCE_CROSSCHECK_RUN_ID,
        "source_config_hash": source.config_hash,
        "source_geometry_hash": SOURCE_GEOMETRY_HASH,
        "geometry_mapping": "day3-air-wire-grid-v1 air variant unchanged",
        "frequency_range_hz": FREQUENCY_RANGE_HZ,
        "frequency_points": FREQUENCY_POINTS,
        "baseline_refinement": baseline_refinement,
        "refinement": refinement,
        "predicted_seconds": predicted,
        "self_convergence_threshold": OPENEMS_SELF_CONVERGENCE_THRESHOLD,
    }
    summary = OpenEMSRefinementRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 1},
        air_variant=source.air_variant,
        refinement=refinement,
        baseline_refinement=baseline_refinement,
        predicted_seconds=predicted,
        actual_wall_seconds=wall,
        baseline_curve=baseline,
        curve=curve,
        adjacent_resonance_shift=shift,
        action=action,
    )
    _write_run(
        run_directory,
        {
            "schema_version": 1,
            "event_type": "patch_openems_self_convergence",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": summary.model_dump(mode="json"),
        },
        summary,
    )
    return summary


def _snapshot(
    prior: ConvergenceRunSummary,
    completed: tuple[NEC2GridRunSummary, ...],
    point: ConvergencePoint,
) -> GapExtrapolationSnapshot:
    points = (*prior.points, *(item.point for item in completed), point)
    grids = tuple(item.grid_intervals for item in points)
    gaps = tuple(item.resonance_relative_gap for item in points)
    return GapExtrapolationSnapshot(
        after_grid_intervals=point.grid_intervals,
        completed_grids=grids,
        completed_gaps=gaps,
        estimated_grid_for_five_percent=power_law_grid_estimate(grids, gaps),
        estimated_grid_for_pearson=grid_estimate_for_pearson(grids, gaps),
    )


def run_nec2_grid(
    repo_root: Path,
    *,
    source: CrossCheckRunSummary,
    prior: ConvergenceRunSummary,
    completed: tuple[NEC2GridRunSummary, ...],
    grid_intervals: int,
    prediction: GridResourcePrediction,
) -> NEC2GridRunSummary:
    """Run one preregistered grid under its already-recorded resource prediction."""

    if not prediction.feasible or prediction.target_grid_intervals != grid_intervals:
        raise CrossCheckError("NEC2 grid cannot start without a matching feasible prediction")
    run_id = f"{ANALYSIS_ID}-nec2-grid{grid_intervals}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"NEC2 patch run already exists: {run_id}")
    wires, grid, spacing = build_wire_grid(source.air_variant, grid_intervals)
    if grid.wire_count != prediction.target_segment_count:
        raise CrossCheckError("resource prediction did not use the generated segment count")
    spec = SimulationSpec(
        name=run_id,
        frequency_range=FREQUENCY_RANGE_HZ,
        frequency_points=FREQUENCY_POINTS,
        far_field_request=None,
    )
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    curve = _curve(
        _run_nec2_grid(
            wires,
            spec,
            repo_root / "tmp",
            timeout_seconds=MAX_SINGLE_RUN_SECONDS,
        )
    )
    wall = time.perf_counter() - started
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"NEC2 grid {grid_intervals} used {curve.solver_mode}")
    gap = abs(
        curve.resonance_frequency_hz - source.openems.resonance_frequency_hz
    ) / source.openems.resonance_frequency_hz
    point = ConvergencePoint(
        grid_intervals=grid_intervals,
        nec2_resonance_frequency_hz=curve.resonance_frequency_hz,
        openems_reference_frequency_hz=source.openems.resonance_frequency_hz,
        resonance_relative_gap=gap,
        minimum_spacing_m=spacing,
        equal_area_wire_radius_m=grid.equal_area_wire_radius_m,
        spacing_to_radius_ratio=spacing / grid.equal_area_wire_radius_m,
        segment_count=grid.wire_count,
        solve_time_seconds=curve.simulation_time_seconds,
        curve=curve,
    )
    extrapolation = _snapshot(prior, completed, point)
    config = {
        "execution_note": "docs/patch-crosscheck-final-execution-note.md",
        "source_crosscheck_run_id": SOURCE_CROSSCHECK_RUN_ID,
        "source_config_hash": source.config_hash,
        "source_geometry_hash": SOURCE_GEOMETRY_HASH,
        "geometry_mapping": "day3-air-wire-grid-v1 equal-area rule unchanged",
        "frequency_range_hz": FREQUENCY_RANGE_HZ,
        "frequency_points": FREQUENCY_POINTS,
        "grid_intervals": grid_intervals,
        "resource_prediction": prediction.model_dump(mode="json"),
    }
    summary = NEC2GridRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=source.seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 1},
        resource_prediction=prediction,
        grid_definition=grid,
        point=point,
        actual_wall_seconds=wall,
        extrapolation=extrapolation,
    )
    _write_run(
        run_directory,
        {
            "schema_version": 1,
            "event_type": "patch_nec2_grid_convergence",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": summary.model_dump(mode="json"),
        },
        summary,
    )
    return summary


def available_memory_bytes() -> int:
    """Return physical memory available immediately before a grid decision."""

    return int(psutil.virtual_memory().available)


def write_series(repo_root: Path, series: PatchConvergenceSeries) -> None:
    """Persist resumable combined state outside version control."""

    path = repo_root / "runs" / ANALYSIS_ID / "series.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(
        (
            json.dumps(
                series.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    os.replace(temporary, path)


def load_openems_run(repo_root: Path, refinement: float) -> OpenEMSRefinementRunSummary:
    """Load one already archived refinement for interruption recovery."""

    return _read_model(
        repo_root
        / "artifacts"
        / "runs"
        / f"{ANALYSIS_ID}-openems-{refinement:g}x"
        / "summary.json",
        OpenEMSRefinementRunSummary,
    )


def load_nec2_run(repo_root: Path, grid: int) -> NEC2GridRunSummary:
    """Load one already archived grid for interruption recovery."""

    return _read_model(
        repo_root
        / "artifacts"
        / "runs"
        / f"{ANALYSIS_ID}-nec2-grid{grid}"
        / "summary.json",
        NEC2GridRunSummary,
    )


def archived_run_ids(repo_root: Path) -> set[str]:
    """Return manifest IDs used to skip only fully archived stages."""

    try:
        payload = json.loads(
            (repo_root / "artifacts" / "runs" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot load evidence manifest: {error}") from error
    return {str(item["run_id"]) for item in payload}


def grid_prediction(
    *,
    baseline_grid: int,
    baseline_seconds: float,
    target_grid: int,
) -> GridResourcePrediction:
    """Capture current available memory in the preregistered prediction."""

    return predict_grid_resources(
        baseline_grid_intervals=baseline_grid,
        baseline_actual_seconds=baseline_seconds,
        target_grid_intervals=target_grid,
        available_memory_bytes=available_memory_bytes(),
    )


def validate_gate(repo_root: Path) -> tuple[CrossCheckRunSummary, ConvergenceRunSummary]:
    """Check anchor and immutable sources before each resumed execution."""

    _load_anchor_gate(repo_root, "day4-dipole-anchor")
    source = _source(repo_root)
    prior = _prior_convergence(repo_root)
    if prior.source_run_id != SOURCE_CROSSCHECK_RUN_ID:
        raise CrossCheckError("Day 4 convergence source changed")
    return source, prior
