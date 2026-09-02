"""Preregistered Day 4 cross-solver anchor and convergence attribution."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.cross_check import (
    AirVariantDefinition,
    CrossCheckError,
    CrossCheckRunSummary,
    SolverCurve,
    WireGridDefinition,
    WireSegment,
    _curve,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationResult, SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.nec2_adapter.card_writer import NEC2CardWriter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

C0 = 299_792_458.0
PROTOCOL_VERSION = "day4-native-curves-v2"
RESONANCE_THRESHOLD = 0.05
CURVE_CORRELATION_THRESHOLD = 0.8
ANCHOR_RESONANCE_THRESHOLD = 0.03
ANCHOR_CORRELATION_THRESHOLD = 0.9
CORRELATION_SAMPLE_COUNT = 201
CONVERGENCE_GRIDS = (6, 12, 24)
FREQUENCY_POINTS = 101

CurveVerdict = Literal["CONFIRMED", "DIVERGENT"]
AttributionVerdict = Literal[
    "instrument_boundary",
    "genuine_anomaly",
    "inconclusive_needs_finer_grid",
]


class CurveDecision(BaseModel):
    """Mechanical protocol-v2 decision based on resonance and curve shape."""

    model_config = ConfigDict(frozen=True)

    resonance_relative_difference: float = Field(ge=0.0)
    resonance_threshold: float = RESONANCE_THRESHOLD
    resonance_threshold_met: bool
    curve_pearson_correlation: float = Field(ge=-1.0, le=1.0)
    curve_correlation_threshold: float = CURVE_CORRELATION_THRESHOLD
    curve_correlation_threshold_met: bool
    s11_depth_difference_db: float = Field(ge=0.0)
    s11_depth_is_record_only: bool = True
    verdict: CurveVerdict


class AnchorDecision(CurveDecision):
    """Stricter protocol-v2 gate that must pass before other comparisons."""

    resonance_threshold: float = ANCHOR_RESONANCE_THRESHOLD
    curve_correlation_threshold: float = ANCHOR_CORRELATION_THRESHOLD


class ConvergencePoint(BaseModel):
    """One real NEC2 grid result compared with the archived openEMS curve."""

    model_config = ConfigDict(frozen=True)

    grid_intervals: int = Field(gt=1)
    nec2_resonance_frequency_hz: float = Field(gt=0.0)
    openems_reference_frequency_hz: float = Field(gt=0.0)
    resonance_relative_gap: float = Field(ge=0.0)
    minimum_spacing_m: float = Field(gt=0.0)
    equal_area_wire_radius_m: float = Field(gt=0.0)
    spacing_to_radius_ratio: float = Field(gt=0.0)
    segment_count: int = Field(gt=0)
    solve_time_seconds: float = Field(ge=0.0)
    curve: SolverCurve


class AttributionDecision(BaseModel):
    """Frozen classification of the three-point wire-grid trend."""

    model_config = ConfigDict(frozen=True)

    verdict: AttributionVerdict
    monotonic_narrowing: bool
    gap_6: float = Field(ge=0.0)
    gap_24: float = Field(ge=0.0)
    gap_24_to_gap_6_ratio: float = Field(ge=0.0)
    estimated_grid_intervals_for_five_percent: int | None = Field(default=None, gt=0)
    extrapolation_method: Literal["log_log_power_law"] = "log_log_power_law"


class AnchorRunSummary(BaseModel):
    """Archive-compatible native dipole anchor evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 2
    evaluation_budget: int = 2
    solver_mode_counts: dict[str, int]
    geometry: dict[str, Any]
    openems: SolverCurve
    nec2: SolverCurve
    decision: AnchorDecision


class ConvergenceRunSummary(BaseModel):
    """Archive-compatible three-grid attribution evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int
    evaluation_budget: int
    solver_mode_counts: dict[str, int]
    source_run_id: str
    source_openems_curve: SolverCurve
    points: tuple[ConvergencePoint, ...]
    attribution: AttributionDecision


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_lf(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def curve_correlation(first: SolverCurve, second: SolverCurve) -> float:
    """Interpolate both dB curves on 201 common-band points and correlate them."""

    first_f = np.asarray(first.frequency_hz, dtype=float)
    second_f = np.asarray(second.frequency_hz, dtype=float)
    low = max(float(first_f.min()), float(second_f.min()))
    high = min(float(first_f.max()), float(second_f.max()))
    if not low < high:
        raise CrossCheckError("solver curves have no common frequency band")
    grid = np.linspace(low, high, CORRELATION_SAMPLE_COUNT)
    first_db = np.interp(grid, first_f, np.asarray(first.s11_db, dtype=float))
    second_db = np.interp(grid, second_f, np.asarray(second.s11_db, dtype=float))
    if float(np.std(first_db)) <= 1e-12 or float(np.std(second_db)) <= 1e-12:
        raise CrossCheckError("Pearson correlation is undefined for a constant curve")
    value = float(np.corrcoef(first_db, second_db)[0, 1])
    if not math.isfinite(value):
        raise CrossCheckError("Pearson correlation is not finite")
    return max(-1.0, min(1.0, value))


def evaluate_curves(
    openems: SolverCurve,
    nec2: SolverCurve,
    *,
    anchor: bool = False,
) -> CurveDecision | AnchorDecision:
    """Apply the frozen protocol-v2 thresholds inclusively."""

    resonance_difference = abs(
        nec2.resonance_frequency_hz - openems.resonance_frequency_hz
    ) / openems.resonance_frequency_hz
    correlation = curve_correlation(openems, nec2)
    depth_difference = abs(nec2.resonance_s11_db - openems.resonance_s11_db)
    resonance_threshold = (
        ANCHOR_RESONANCE_THRESHOLD if anchor else RESONANCE_THRESHOLD
    )
    correlation_threshold = (
        ANCHOR_CORRELATION_THRESHOLD if anchor else CURVE_CORRELATION_THRESHOLD
    )
    resonance_ok = resonance_difference <= resonance_threshold
    correlation_ok = correlation >= correlation_threshold
    values = {
        "resonance_relative_difference": resonance_difference,
        "resonance_threshold_met": resonance_ok,
        "curve_pearson_correlation": correlation,
        "curve_correlation_threshold_met": correlation_ok,
        "s11_depth_difference_db": depth_difference,
        "verdict": "CONFIRMED" if resonance_ok and correlation_ok else "DIVERGENT",
    }
    if anchor:
        return AnchorDecision.model_validate(values)
    return CurveDecision.model_validate(values)


def evaluate_attribution(
    points: tuple[ConvergencePoint, ...],
) -> AttributionDecision:
    """Apply the preregistered 6/12/24 convergence attribution rule."""

    by_grid = {point.grid_intervals: point for point in points}
    missing = set(CONVERGENCE_GRIDS) - by_grid.keys()
    if missing:
        raise CrossCheckError(f"convergence evidence lacks grids {sorted(missing)}")
    ordered = [by_grid[grid] for grid in CONVERGENCE_GRIDS]
    gaps = [point.resonance_relative_gap for point in ordered]
    monotonic = all(left >= right for left, right in zip(gaps, gaps[1:], strict=False))
    gap_6 = gaps[0]
    gap_24 = gaps[-1]
    ratio = gap_24 / gap_6 if gap_6 > 0.0 else 0.0
    if monotonic and gap_24 < 0.5 * gap_6:
        verdict: AttributionVerdict = "instrument_boundary"
    elif gap_24 >= 0.8 * gap_6:
        verdict = "genuine_anomaly"
    else:
        verdict = "inconclusive_needs_finer_grid"
    estimate = _estimate_grid_for_gap(ordered, 0.05)
    return AttributionDecision(
        verdict=verdict,
        monotonic_narrowing=monotonic,
        gap_6=gap_6,
        gap_24=gap_24,
        gap_24_to_gap_6_ratio=ratio,
        estimated_grid_intervals_for_five_percent=estimate,
    )


def _estimate_grid_for_gap(
    points: list[ConvergencePoint], target_gap: float
) -> int | None:
    grids = np.asarray([point.grid_intervals for point in points], dtype=float)
    gaps = np.asarray([point.resonance_relative_gap for point in points], dtype=float)
    if np.any(gaps <= 0.0) or not all(
        left >= right for left, right in zip(gaps, gaps[1:], strict=False)
    ):
        return None
    slope, intercept = np.polyfit(np.log(grids), np.log(gaps), 1)
    exponent = -float(slope)
    if exponent <= 0.0:
        return None
    coefficient = math.exp(float(intercept))
    estimate = math.ceil((coefficient / target_gap) ** (1.0 / exponent))
    return max(points[-1].grid_intervals + 1, int(estimate))


def _axis_nodes(
    low: float, high: float, extra: float, grid_intervals: int
) -> tuple[float, ...]:
    if not low < extra < high:
        return tuple(
            float(value) for value in np.linspace(low, high, grid_intervals + 1)
        )
    fraction_left = (extra - low) / (high - low)
    left_intervals = min(
        max(round(grid_intervals * fraction_left), 1), grid_intervals - 1
    )
    right_intervals = grid_intervals - left_intervals
    left = [float(value) for value in np.linspace(low, extra, left_intervals + 1)]
    right = [float(value) for value in np.linspace(extra, high, right_intervals + 1)]
    return (*left, *right[1:])


def _plane_edges(
    *,
    length: float,
    width: float,
    z: float,
    feed_x: float,
    radius: float,
    first_tag: int,
    grid_intervals: int,
) -> tuple[list[WireSegment], int, float]:
    x_nodes = _axis_nodes(-length / 2.0, length / 2.0, feed_x, grid_intervals)
    y_nodes = _axis_nodes(-width / 2.0, width / 2.0, 0.0, grid_intervals)
    wires: list[WireSegment] = []
    tag = first_tag
    total_length = 0.0
    for y in y_nodes:
        for start_x, stop_x in zip(x_nodes, x_nodes[1:], strict=False):
            wires.append(
                WireSegment(
                    tag=tag,
                    start_m=(start_x, y, z),
                    stop_m=(stop_x, y, z),
                    radius_m=radius,
                )
            )
            tag += 1
            total_length += stop_x - start_x
    for x in x_nodes:
        for start_y, stop_y in zip(y_nodes, y_nodes[1:], strict=False):
            wires.append(
                WireSegment(
                    tag=tag,
                    start_m=(x, start_y, z),
                    stop_m=(x, stop_y, z),
                    radius_m=radius,
                )
            )
            tag += 1
            total_length += stop_y - start_y
    return wires, tag, total_length


def build_wire_grid(
    definition: AirVariantDefinition, grid_intervals: int
) -> tuple[tuple[WireSegment, ...], WireGridDefinition, float]:
    """Build one equal-area grid and return its shortest spacing."""

    if grid_intervals <= 1:
        raise CrossCheckError("grid_intervals must exceed one")
    patch_x = _axis_nodes(
        -definition.patch_length_m / 2.0,
        definition.patch_length_m / 2.0,
        definition.feed_x_m,
        grid_intervals,
    )
    patch_y = _axis_nodes(
        -definition.patch_width_m / 2.0,
        definition.patch_width_m / 2.0,
        definition.feed_y_m,
        grid_intervals,
    )
    ground_x = _axis_nodes(
        -definition.ground_length_m / 2.0,
        definition.ground_length_m / 2.0,
        definition.feed_x_m,
        grid_intervals,
    )
    ground_y = _axis_nodes(
        -definition.ground_width_m / 2.0,
        definition.ground_width_m / 2.0,
        definition.feed_y_m,
        grid_intervals,
    )
    total_length = (
        len(patch_y) * definition.patch_length_m
        + len(patch_x) * definition.patch_width_m
        + len(ground_y) * definition.ground_length_m
        + len(ground_x) * definition.ground_width_m
    )
    metal_area = definition.patch_metal_area_m2 + definition.ground_metal_area_m2
    radius = metal_area / (2.0 * math.pi * total_length)
    feed_radius = min(radius, definition.air_gap_m / 20.0)
    feed = WireSegment(
        tag=1,
        start_m=(definition.feed_x_m, definition.feed_y_m, 0.0),
        stop_m=(definition.feed_x_m, definition.feed_y_m, definition.air_gap_m),
        radius_m=feed_radius,
    )
    patch, next_tag, patch_length = _plane_edges(
        length=definition.patch_length_m,
        width=definition.patch_width_m,
        z=definition.air_gap_m,
        feed_x=definition.feed_x_m,
        radius=radius,
        first_tag=2,
        grid_intervals=grid_intervals,
    )
    ground, _, ground_length = _plane_edges(
        length=definition.ground_length_m,
        width=definition.ground_width_m,
        z=0.0,
        feed_x=definition.feed_x_m,
        radius=radius,
        first_tag=next_tag,
        grid_intervals=grid_intervals,
    )
    wires = (feed, *patch, *ground)
    minimum_spacing = min(
        math.dist(wire.start_m, wire.stop_m) for wire in (*patch, *ground)
    )
    grid = WireGridDefinition(
        grid_intervals=grid_intervals,
        wire_count=len(wires),
        grid_wire_count=len(patch) + len(ground),
        total_grid_wire_length_m=patch_length + ground_length,
        represented_metal_area_m2=metal_area,
        equal_area_wire_radius_m=radius,
        feed_wire_radius_m=feed_radius,
    )
    return wires, grid, minimum_spacing


def _nec_deck(
    wires: tuple[WireSegment, ...], frequency_range: tuple[float, float], points: int
) -> NEC2CardWriter:
    writer = NEC2CardWriter(title=f"YAF {PROTOCOL_VERSION}")
    for wire in wires:
        writer.cards.append(
            writer.gw_card(
                wire.tag, 1, *wire.start_m, *wire.stop_m, wire.radius_m
            )
        )
    writer.cards.append(writer.ge_card(0))
    writer.cards.append(writer.ex_card(excitation_type=0, tag=1, segment=1))
    writer.cards.append(
        writer.fr_card((frequency_range[0] / 1e6, frequency_range[1] / 1e6, points))
    )
    writer.cards.append(writer.rp_card(n_theta=3, n_phi=1, dtheta=90.0, dphi=0.0))
    return writer


def _run_nec2_grid(
    wires: tuple[WireSegment, ...],
    spec: SimulationSpec,
    temporary_root: Path,
    *,
    timeout_seconds: float = 1800.0,
) -> SimulationResult:
    adapter = NEC2Adapter()
    runner = adapter._resolve_runner()
    if runner is None:
        raise CrossCheckError("real nec2c is unavailable through PATH or WSL")
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yv2_", dir=temporary_root) as directory:
        root = Path(directory)
        input_path = root / "study.nec"
        output_path = root / "study.out"
        input_path.write_bytes(
            _nec_deck(wires, spec.frequency_range, spec.frequency_points).to_bytes()
        )
        started = time.monotonic()
        try:
            process = subprocess.run(
                [
                    *runner,
                    "-i",
                    adapter._solver_path(input_path, runner),
                    "-o",
                    adapter._solver_path(output_path, runner),
                ],
                capture_output=True,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CrossCheckError(f"nec2c execution failed: {error}") from error
        elapsed = time.monotonic() - started
        if process.returncode != 0 or not output_path.is_file():
            stderr = process.stderr.decode("utf-8", errors="replace")[-500:]
            raise CrossCheckError(f"nec2c exited with {process.returncode}: {stderr}")
        result = adapter._parse_nec_output(
            output_path, spec, str(uuid.uuid4()), elapsed
        )
        result.solver_metadata["runner"] = " ".join(runner)
        result.solver_metadata["cross_check_protocol"] = PROTOCOL_VERSION
        return result


def _anchor_geometry() -> Geometry:
    length = C0 / (2.0 * 2.45e9)
    return Geometry(
        name="2.45 GHz native half-wave dipole anchor",
        vertices=[[0.0, 0.0, -length / 2.0], [0.0, 0.0, length / 2.0]],
        faces=[[0, 1]],
        metadata={
            "antenna_class": "wire_dipole_anchor",
            "center_frequency_hz": 2.45e9,
            "length_m": length,
            "wire_radius_m": 0.0005,
            "protocol_version": PROTOCOL_VERSION,
        },
    )


def _write_run(
    run_directory: Path, records: list[dict[str, Any]], summary: BaseModel
) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    log = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for record in records
    )
    (run_directory / "log.jsonl").write_bytes(log.encode("utf-8"))
    _write_json_lf(run_directory / "summary.json", summary.model_dump(mode="json"))


async def run_anchor(repo_root: Path, run_id: str = "day4-dipole-anchor") -> AnchorRunSummary:
    """Run the native 2.45 GHz dipole gate and persist both complete curves."""

    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"anchor run directory already exists: {run_id}")
    geometry = _anchor_geometry()
    spec = SimulationSpec(
        name=run_id,
        frequency_range=(1.8e9, 3.1e9),
        frequency_points=FREQUENCY_POINTS,
        far_field_request=None,
    )
    config = {
        "protocol_version": PROTOCOL_VERSION,
        "anchor_center_frequency_hz": 2.45e9,
        "geometry": geometry.metadata,
        "frequency_range_hz": spec.frequency_range,
        "frequency_points": spec.frequency_points,
        "resonance_threshold": ANCHOR_RESONANCE_THRESHOLD,
        "curve_correlation_threshold": ANCHOR_CORRELATION_THRESHOLD,
        "correlation_sample_count": CORRELATION_SAMPLE_COUNT,
    }
    started_at = datetime.now(UTC)
    results: dict[str, SolverCurve] = {}
    for name, adapter in (
        ("nec2", NEC2Adapter()),
        ("openems", OpenEMSAdapter()),
    ):
        mesh = await adapter.mesh(geometry, spec)
        curve = _curve(await adapter.solve(mesh, spec))
        if curve.solver_mode != "subprocess":
            raise CrossCheckError(f"{name} anchor is not real: {curve.solver_mode}")
        results[name] = curve
    decision = evaluate_curves(results["openems"], results["nec2"], anchor=True)
    if not isinstance(decision, AnchorDecision):
        raise AssertionError("anchor evaluation returned the wrong decision model")
    summary = AnchorRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 2},
        geometry=geometry.metadata,
        openems=results["openems"],
        nec2=results["nec2"],
        decision=decision,
    )
    records = [
        {
            "schema_version": 1,
            "event_type": "anchor_solver_result",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": PROTOCOL_VERSION,
            "curve": curve.model_dump(mode="json"),
        }
        for curve in (summary.openems, summary.nec2)
    ]
    _write_run(run_directory, records, summary)
    return summary


def _load_anchor_gate(repo_root: Path, anchor_run_id: str) -> AnchorRunSummary:
    path = repo_root / "artifacts" / "runs" / anchor_run_id / "summary.json"
    try:
        summary = AnchorRunSummary.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"a valid archived anchor is required: {error}") from error
    if summary.decision.verdict != "CONFIRMED":
        raise CrossCheckError("archived anchor failed; convergence is forbidden")
    return summary


def run_convergence(
    repo_root: Path,
    *,
    source_run_id: str = "day3-crosscheck-wifi24",
    run_id: str = "day4-attribution-wifi24",
    anchor_run_id: str = "day4-dipole-anchor",
) -> ConvergenceRunSummary:
    """Run the frozen 6/12/24 NEC2 study against archived openEMS evidence."""

    _load_anchor_gate(repo_root, anchor_run_id)
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"convergence run directory already exists: {run_id}")
    source_path = repo_root / "artifacts" / "runs" / source_run_id / "summary.json"
    try:
        source = CrossCheckRunSummary.model_validate_json(
            source_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load archived Day 3 source: {error}") from error
    started_at = datetime.now(UTC)
    spec = SimulationSpec(
        name=run_id,
        frequency_range=(
            source.openems.frequency_hz[0],
            source.openems.frequency_hz[-1],
        ),
        frequency_points=len(source.openems.frequency_hz),
        far_field_request=None,
    )
    points: list[ConvergencePoint] = []
    for grid_intervals in CONVERGENCE_GRIDS:
        wires, grid, spacing = build_wire_grid(source.air_variant, grid_intervals)
        curve = _curve(_run_nec2_grid(wires, spec, repo_root / "tmp"))
        if curve.solver_mode != "subprocess":
            raise CrossCheckError(f"grid {grid_intervals} used {curve.solver_mode}")
        gap = abs(
            curve.resonance_frequency_hz
            - source.openems.resonance_frequency_hz
        ) / source.openems.resonance_frequency_hz
        points.append(
            ConvergencePoint(
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
        )
    point_tuple = tuple(points)
    attribution = evaluate_attribution(point_tuple)
    config = {
        "protocol_version": PROTOCOL_VERSION,
        "source_run_id": source_run_id,
        "source_config_hash": source.config_hash,
        "openems_reference_reused": True,
        "grid_intervals": CONVERGENCE_GRIDS,
        "wire_radius_rule": "equal_exposed_area",
        "attribution_thresholds": {
            "instrument_boundary_ratio": 0.5,
            "genuine_anomaly_ratio": 0.8,
            "target_gap": 0.05,
        },
    }
    summary = ConvergenceRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=source.seed,
        config_hash=_canonical_hash(config),
        config=config,
        steps_completed=len(points),
        evaluation_budget=len(points),
        solver_mode_counts={"subprocess": len(points)},
        source_run_id=source_run_id,
        source_openems_curve=source.openems,
        points=point_tuple,
        attribution=attribution,
    )
    records = [
        {
            "schema_version": 1,
            "event_type": "convergence_solver_result",
            "run_id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": PROTOCOL_VERSION,
            "source_run_id": source_run_id,
            "point": point.model_dump(mode="json"),
        }
        for point in points
    ]
    _write_run(run_directory, records, summary)
    return summary
