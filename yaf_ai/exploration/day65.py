"""Pre-registered Day 6.5 renderer known-answer and repair evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.environment import geometry_hash
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

DAY65_PROTOCOL_VERSION = "day65-freeform-repair-v12"
DAY65_ROTATION_RUN_ID = "day65-freeform-rotation-invariance-r12"
DAY65_ROTATION_SWEEP_HZ = (1.5e9, 3.5e9)
DAY65_ROTATION_POINTS = 201
DAY65_DIPOLE_LENGTH_M = 299_792_458.0 / (2.0 * 2.45e9)
DAY65_FEED_GAP_M = 0.0006
DAY65_WIRE_RADIUS_M = 0.00005
DAY65_ROTATION_FREQUENCY_THRESHOLD = 0.02
DAY65_ROTATION_DEPTH_THRESHOLD_DB = 1.5
DAY65_ROTATION_PEARSON_THRESHOLD = 0.95

RotationName = Literal["y_axis", "yz45", "z_axis"]
SolverName = Literal["nec2", "openems"]


class RotationResonance(BaseModel):
    """Known-answer resonance validity for one orientation and solver."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    frequency_hz: float = Field(gt=0.0)
    s11_db: float
    local_minimum: bool
    edge_guard_met: bool
    depth_met: bool
    valid: bool


class RotationOrientationResult(BaseModel):
    """Both native solver curves for one physical dipole orientation."""

    model_config = ConfigDict(frozen=True)

    orientation: RotationName
    direction: tuple[float, float, float]
    geometry_hash: str
    nec2: SolverCurve
    openems: SolverCurve
    nec2_resonance: RotationResonance
    openems_resonance: RotationResonance


class RotationPairDecision(BaseModel):
    """One pairwise application of the frozen invariance thresholds."""

    model_config = ConfigDict(frozen=True)

    solver: SolverName
    first: RotationName
    second: RotationName
    frequency_relative_difference: float = Field(ge=0.0)
    s11_depth_difference_db: float = Field(ge=0.0)
    pearson: float = Field(ge=-1.0, le=1.0)
    both_resonances_valid: bool
    passed: bool


class Day65RotationSummary(BaseModel):
    """Archive-compatible six-solve rotation-invariance evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str = DAY65_ROTATION_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 6
    evaluation_budget: int = 6
    solver_mode_counts: dict[str, int]
    orientations: tuple[
        RotationOrientationResult,
        RotationOrientationResult,
        RotationOrientationResult,
    ]
    comparisons: tuple[RotationPairDecision, ...]
    openems_release_gate_passed: bool
    nec2_control_passed: bool


class RotationStageRecord(BaseModel):
    """Crash-safe draft record for one fully solved orientation."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    config_hash: str
    started_at: datetime
    finished_at: datetime
    result: RotationOrientationResult


def _canonical_hash(payload: object) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def load_rotation_stage(
    path: Path,
    *,
    run_id: str,
    config_hash: str,
    orientation: RotationName,
) -> RotationStageRecord:
    """Load only a staging record produced by the exact frozen instrument."""

    stage = RotationStageRecord.model_validate_json(path.read_text(encoding="utf-8"))
    if (
        stage.run_id != run_id
        or stage.config_hash != config_hash
        or stage.result.orientation != orientation
    ):
        raise CrossCheckError(
            f"Day 6.5 staging mismatch for {orientation}; refusing reuse"
        )
    return stage


def build_rotation_dipole(orientation: RotationName) -> Geometry:
    """Build the same center-fed half-wave wire in one frozen orientation."""

    root_half = math.sqrt(0.5)
    directions: dict[RotationName, tuple[float, float, float]] = {
        "y_axis": (0.0, 1.0, 0.0),
        "yz45": (0.0, root_half, root_half),
        "z_axis": (0.0, 0.0, 1.0),
    }
    direction = directions[orientation]
    positive_feed = (DAY65_FEED_GAP_M / 2.0, 0.0, 0.0)
    negative_feed = (-DAY65_FEED_GAP_M / 2.0, 0.0, 0.0)
    arm_length = DAY65_DIPOLE_LENGTH_M / 2.0
    positive_tip = tuple(
        positive_feed[index] + direction[index] * arm_length
        for index in range(3)
    )
    negative_tip = tuple(
        negative_feed[index] - direction[index] * arm_length
        for index in range(3)
    )
    return Geometry(
        name=f"day65_rotation_{orientation}",
        vertices=[negative_feed, positive_feed, positive_tip, negative_tip],
        faces=[[0, 1], [1, 2], [0, 3]],
        metadata={
            "antenna_class": "freeform_wire_3d",
            "wire_radius_m": DAY65_WIRE_RADIUS_M,
            "feed_gap_m": DAY65_FEED_GAP_M,
            "positive_edge_count": 1,
            "total_wire_length_m": DAY65_DIPOLE_LENGTH_M,
            "rotation_orientation": orientation,
            "control_positive": [positive_feed, positive_tip],
            "control_negative": [negative_feed, negative_tip],
        },
    )


def rotation_resonance(curve: SolverCurve) -> RotationResonance:
    """Apply the frozen -6 dB and three-bin edge guard to a full sweep."""

    index = min(range(len(curve.s11_db)), key=curve.s11_db.__getitem__)
    local = (
        0 < index < len(curve.s11_db) - 1
        and curve.s11_db[index] <= curve.s11_db[index - 1]
        and curve.s11_db[index] <= curve.s11_db[index + 1]
        and (
            curve.s11_db[index] < curve.s11_db[index - 1]
            or curve.s11_db[index] < curve.s11_db[index + 1]
        )
    )
    edge = 3 <= index <= len(curve.s11_db) - 4
    depth = curve.s11_db[index] <= -6.0
    return RotationResonance(
        index=index,
        frequency_hz=curve.frequency_hz[index],
        s11_db=curve.s11_db[index],
        local_minimum=local,
        edge_guard_met=edge,
        depth_met=depth,
        valid=local and edge and depth,
    )


def _pearson(first: SolverCurve, second: SolverCurve) -> float:
    frequencies = np.asarray(first.frequency_hz, dtype=float)
    left = np.asarray(first.s11_db, dtype=float)
    right = np.interp(
        frequencies,
        np.asarray(second.frequency_hz, dtype=float),
        np.asarray(second.s11_db, dtype=float),
    )
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def compare_rotation_pair(
    first: RotationOrientationResult,
    second: RotationOrientationResult,
    solver: SolverName,
) -> RotationPairDecision:
    """Compare two orientations with the preregistered symmetric frequency gap."""

    first_curve = first.nec2 if solver == "nec2" else first.openems
    second_curve = second.nec2 if solver == "nec2" else second.openems
    first_resonance = (
        first.nec2_resonance if solver == "nec2" else first.openems_resonance
    )
    second_resonance = (
        second.nec2_resonance if solver == "nec2" else second.openems_resonance
    )
    denominator = (
        first_resonance.frequency_hz + second_resonance.frequency_hz
    ) / 2.0
    frequency_gap = abs(
        first_resonance.frequency_hz - second_resonance.frequency_hz
    ) / denominator
    depth_gap = abs(first_resonance.s11_db - second_resonance.s11_db)
    correlation = _pearson(first_curve, second_curve)
    valid = first_resonance.valid and second_resonance.valid
    return RotationPairDecision(
        solver=solver,
        first=first.orientation,
        second=second.orientation,
        frequency_relative_difference=frequency_gap,
        s11_depth_difference_db=depth_gap,
        pearson=correlation,
        both_resonances_valid=valid,
        passed=(
            valid
            and frequency_gap <= DAY65_ROTATION_FREQUENCY_THRESHOLD
            and depth_gap <= DAY65_ROTATION_DEPTH_THRESHOLD_DB
            and correlation >= DAY65_ROTATION_PEARSON_THRESHOLD
        ),
    )


async def run_rotation_invariance(repo_root: Path) -> Day65RotationSummary:
    """Run all six real solves and persist one immutable known-answer run."""

    run_directory = repo_root / "runs" / DAY65_ROTATION_RUN_ID
    if run_directory.exists():
        return Day65RotationSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    config: dict[str, Any] = {
        "protocol_version": DAY65_PROTOCOL_VERSION,
        "orientations": ["y_axis", "yz45", "z_axis"],
        "frequency_range_hz": DAY65_ROTATION_SWEEP_HZ,
        "frequency_points": DAY65_ROTATION_POINTS,
        "dipole_length_m": DAY65_DIPOLE_LENGTH_M,
        "feed_gap_m": DAY65_FEED_GAP_M,
        "wire_radius_m": DAY65_WIRE_RADIUS_M,
        "openems_conductor_primitive": "sphere-ended-wire",
        "openems_surrogate_radius_m": 0.00025,
        "openems_local_grid_step_m": 0.0005,
        "openems_local_grid_partition": "equal-box-feed-intervals-v1",
        "openems_timeout_seconds": 7200.0,
        "openems_mesh_refinement": 6.0,
        "openems_number_of_timesteps": 240000,
        "nec2_segments_per_wavelength": 160,
        "frequency_relative_difference_threshold": DAY65_ROTATION_FREQUENCY_THRESHOLD,
        "s11_depth_difference_threshold_db": DAY65_ROTATION_DEPTH_THRESHOLD_DB,
        "pearson_threshold": DAY65_ROTATION_PEARSON_THRESHOLD,
    }
    spec = SimulationSpec(
        name=DAY65_ROTATION_RUN_ID,
        frequency_range=DAY65_ROTATION_SWEEP_HZ,
        frequency_points=DAY65_ROTATION_POINTS,
        far_field_request=None,
        solver_settings={
            "openems_mesh_refinement": 6.0,
            "openems_base_timesteps": 40000,
            "openems_timeout_seconds": 7200.0,
            "nec2_segments_per_wavelength": 160,
            "nec2_timeout_seconds": 1800.0,
        },
    )
    config_hash = _canonical_hash(config)
    staging_directory = repo_root / "runs" / f".{DAY65_ROTATION_RUN_ID}-staging"
    stage_records: list[RotationStageRecord] = []
    results: list[RotationOrientationResult] = []
    for orientation in ("y_axis", "yz45", "z_axis"):
        stage_path = staging_directory / f"{orientation}.json"
        if stage_path.exists():
            stage = load_rotation_stage(
                stage_path,
                run_id=DAY65_ROTATION_RUN_ID,
                config_hash=config_hash,
                orientation=orientation,
            )
            results.append(stage.result)
            stage_records.append(stage)
            print(f"resumed completed orientation: {orientation}", flush=True)
            continue
        orientation_started_at = datetime.now(UTC)
        geometry = build_rotation_dipole(orientation)
        curves: dict[SolverName, SolverCurve] = {}
        adapters: tuple[
            tuple[SolverName, NEC2Adapter | OpenEMSAdapter], ...
        ] = (
            ("nec2", NEC2Adapter()),
            ("openems", OpenEMSAdapter()),
        )
        for solver, adapter in adapters:
            mesh = await adapter.mesh(geometry, spec)
            curve = _curve(await adapter.solve(mesh, spec))
            if curve.solver_mode != "subprocess":
                raise CrossCheckError(
                    f"Day 6.5 {orientation} {solver} is not real: {curve.solver_mode}"
                )
            curves[solver] = curve
        result = RotationOrientationResult(
            orientation=orientation,
            direction=tuple(
                float(value) for value in geometry.metadata["control_positive"][1]
            ),
            geometry_hash=geometry_hash(geometry),
            nec2=curves["nec2"],
            openems=curves["openems"],
            nec2_resonance=rotation_resonance(curves["nec2"]),
            openems_resonance=rotation_resonance(curves["openems"]),
        )
        stage = RotationStageRecord(
            run_id=DAY65_ROTATION_RUN_ID,
            config_hash=config_hash,
            started_at=orientation_started_at,
            finished_at=datetime.now(UTC),
            result=result,
        )
        _write_json(stage_path, stage.model_dump(mode="json"))
        results.append(result)
        stage_records.append(stage)
        print(f"staged completed orientation: {orientation}", flush=True)
    comparison_solvers: tuple[SolverName, SolverName] = ("nec2", "openems")
    comparisons = tuple(
        compare_rotation_pair(first, second, solver)
        for solver in comparison_solvers
        for first, second in combinations(results, 2)
    )
    openems_passed = all(
        item.passed for item in comparisons if item.solver == "openems"
    )
    nec2_passed = all(item.passed for item in comparisons if item.solver == "nec2")
    summary = Day65RotationSummary(
        started_at=min(stage.started_at for stage in stage_records),
        finished_at=datetime.now(UTC),
        config_hash=config_hash,
        config=config,
        solver_mode_counts={"subprocess": 6},
        orientations=(results[0], results[1], results[2]),
        comparisons=comparisons,
        openems_release_gate_passed=openems_passed,
        nec2_control_passed=nec2_passed,
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    records = []
    for result in results:
        for solver in ("nec2", "openems"):
            records.append(
                {
                    "schema_version": 1,
                    "event_type": "day65_rotation_invariance_result",
                    "run_id": DAY65_ROTATION_RUN_ID,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "orientation": result.orientation,
                    "solver": solver,
                    "geometry_hash": result.geometry_hash,
                    "curve": getattr(result, solver).model_dump(mode="json"),
                    "resonance": getattr(
                        result, f"{solver}_resonance"
                    ).model_dump(mode="json"),
                }
            )
    (run_directory / "log.jsonl").write_bytes(
        "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            for record in records
        ).encode("utf-8")
    )
    _write_json(run_directory / "summary.json", summary.model_dump(mode="json"))
    return summary
