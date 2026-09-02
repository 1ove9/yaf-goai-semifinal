"""Preregistered openEMS-to-NEC2 verification for air-substrate variants."""

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

from yaf_ai.exploration.analysis import _write_text_lf
from yaf_ai.exploration.baselines import _proposal_from_parameters
from yaf_ai.exploration.environment import (
    ExplorationConfig,
    geometry_hash,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationResult, SimulationSpec
from yaf_core.geometry.parametric import ParametricGenerator
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.nec2_adapter.card_writer import NEC2CardWriter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

C0 = 299_792_458.0
PROTOCOL_VERSION = "day3-air-wire-grid-v1"
MAX_RESONANCE_RELATIVE_DIFFERENCE = 0.05
MAX_S11_DEPTH_DIFFERENCE_DB = 3.0
GRID_INTERVALS = 6
FREQUENCY_POINTS = 51

CrossSolverVerdict = Literal["CONFIRMED", "DIVERGENT"]


class CrossCheckError(RuntimeError):
    """Raised when real, source-addressed cross-check evidence cannot be produced."""


class ArchivedDesignRecord(BaseModel):
    """Archived top-design fields needed for exact reconstruction."""

    model_config = ConfigDict(extra="allow", frozen=True)

    geometry_hash: str
    step_index: int = Field(ge=0)
    proposal_parameters: dict[str, float]
    proposer: str
    score: float


class ArchivedRunSummary(BaseModel):
    """Archived Day 2 summary fields consumed by a cross-check."""

    model_config = ConfigDict(extra="allow", frozen=True)

    run_id: str
    seed: int
    config_hash: str
    config: dict[str, Any]
    top_designs: tuple[ArchivedDesignRecord, ...]


class AirVariantDefinition(BaseModel):
    """Auditable FR4-to-air transformation with invariant conductor geometry."""

    model_config = ConfigDict(frozen=True)

    patch_length_m: float = Field(gt=0.0)
    patch_width_m: float = Field(gt=0.0)
    patch_metal_area_m2: float = Field(gt=0.0)
    ground_length_m: float = Field(gt=0.0)
    ground_width_m: float = Field(gt=0.0)
    ground_metal_area_m2: float = Field(gt=0.0)
    air_gap_m: float = Field(gt=0.0)
    feed_x_m: float
    feed_y_m: float
    original_eps_r: float = Field(gt=0.0)
    variant_eps_r: float = 1.0
    variant_loss_tangent: float = 0.0


class WireSegment(BaseModel):
    """One NEC2 wire-grid edge with an explicit radius and source tag."""

    model_config = ConfigDict(frozen=True)

    tag: int = Field(gt=0)
    start_m: tuple[float, float, float]
    stop_m: tuple[float, float, float]
    radius_m: float = Field(gt=0.0)


class WireGridDefinition(BaseModel):
    """Frozen finite patch/ground grid approximation for NEC2."""

    model_config = ConfigDict(frozen=True)

    grid_intervals: int = Field(gt=1)
    wire_count: int = Field(gt=0)
    grid_wire_count: int = Field(gt=0)
    total_grid_wire_length_m: float = Field(gt=0.0)
    represented_metal_area_m2: float = Field(gt=0.0)
    equal_area_wire_radius_m: float = Field(gt=0.0)
    feed_wire_radius_m: float = Field(gt=0.0)
    feed_tag: int = 1
    ground_handling: Literal["explicit_finite_wire_grid"] = (
        "explicit_finite_wire_grid"
    )


class SolverCurve(BaseModel):
    """Traceable real-solver S11 curve and extracted resonance."""

    model_config = ConfigDict(frozen=True)

    solver_name: str
    solver_mode: str
    frequency_hz: tuple[float, ...]
    s11_db: tuple[float, ...]
    curve_downsample_stride: int = 1
    resonance_frequency_hz: float = Field(gt=0.0)
    resonance_s11_db: float
    simulation_time_seconds: float = Field(ge=0.0)


class CrossCheckDecision(BaseModel):
    """Mechanical application of the frozen two-part confirmation rule."""

    model_config = ConfigDict(frozen=True)

    resonance_relative_difference: float = Field(ge=0.0)
    resonance_threshold: float = MAX_RESONANCE_RELATIVE_DIFFERENCE
    resonance_threshold_met: bool
    s11_depth_difference_db: float = Field(ge=0.0)
    s11_depth_threshold_db: float = MAX_S11_DEPTH_DIFFERENCE_DB
    s11_depth_threshold_met: bool
    verdict: CrossSolverVerdict


class CrossCheckLogRecord(BaseModel):
    """One of the two solver records written to the cross-check JSONL."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    event_type: Literal["cross_solver_result"] = "cross_solver_result"
    run_id: str
    source_run_id: str
    source_design_index: int
    source_geometry_hash: str
    spec_name: str
    timestamp: datetime
    protocol_version: str = PROTOCOL_VERSION
    air_variant: AirVariantDefinition
    wire_grid: WireGridDefinition
    curve: SolverCurve


class CrossCheckRunSummary(BaseModel):
    """Archive-compatible summary containing both curves and decision basis."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 2
    evaluation_budget: int = 2
    solver_mode_counts: dict[str, int]
    source_run_id: str
    source_design_index: int
    source_geometry_hash: str
    spec_name: str
    air_variant: AirVariantDefinition
    wire_grid: WireGridDefinition
    openems: SolverCurve
    nec2: SolverCurve
    decision: CrossCheckDecision


class CrossCheckStateRecord(BaseModel):
    """One completed cross-check registered for analysis and resume safety."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    source_run_id: str
    spec_name: str
    verdict: CrossSolverVerdict


class CrossCheckFailureRecord(BaseModel):
    """A pre-decision execution failure retained without inventing a verdict."""

    model_config = ConfigDict(frozen=True)

    source_run_id: str
    source_design_index: int
    timestamp: datetime
    error: str
    result_status: Literal["no_numeric_decision"] = "no_numeric_decision"


class CrossCheckState(BaseModel):
    """Small durable index for the three-spec Day 3 cross-check set."""

    model_config = ConfigDict(frozen=True)

    batch_id: str
    runs: tuple[CrossCheckStateRecord, ...] = ()
    failed_attempts: tuple[CrossCheckFailureRecord, ...] = ()


class CrossCheckDiscoveryDecision(BaseModel):
    """Day 2 discovery verdict after applying one cross-solver result."""

    model_config = ConfigDict(frozen=True)

    spec: str
    cross_check_run_id: str
    cross_solver_verdict: CrossSolverVerdict
    openems_resonance_frequency_hz: float
    openems_resonance_s11_db: float
    nec2_resonance_frequency_hz: float
    nec2_resonance_s11_db: float
    resonance_relative_difference: float
    s11_depth_difference_db: float
    day2_improvement_fraction: float
    day2_improvement_threshold_met: bool
    verdict: Literal["confirmed_improvement", "insufficient_evidence"]
    reason: str
    source_run_ids: tuple[str, ...]


class CrossCheckAnalysisSummary(BaseModel):
    """Machine-readable three-spec report with source-addressed decisions."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str
    protocol_version: str = PROTOCOL_VERSION
    decisions: tuple[CrossCheckDiscoveryDecision, ...]
    failed_attempts: tuple[CrossCheckFailureRecord, ...] = ()


def _canonical_hash(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_json_lf(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def reconstruct_archived_design(
    source_run_id: str,
    design_index: int,
    *,
    artifacts_root: Path,
) -> tuple[ArchivedRunSummary, ArchivedDesignRecord, ExplorationConfig, Geometry]:
    """Rebuild a Day 2 design solely from archived config and parameters."""

    summary_path = artifacts_root / source_run_id / "summary.json"
    try:
        summary = ArchivedRunSummary.model_validate_json(
            summary_path.read_text(encoding="utf-8")
        )
        config = ExplorationConfig.model_validate(summary.config)
        design = summary.top_designs[design_index]
    except (OSError, ValidationError, IndexError) as error:
        raise CrossCheckError(
            f"cannot load archived design {source_run_id}[{design_index}]: {error}"
        ) from error
    if summary.run_id != source_run_id:
        raise CrossCheckError("archived summary run_id does not match its directory")
    proposal = _proposal_from_parameters(
        config,
        design.proposal_parameters,
        design.proposer,
    )
    actual_hash = geometry_hash(proposal.geometry)
    if actual_hash != design.geometry_hash:
        raise CrossCheckError(
            f"reconstructed geometry hash mismatch: expected={design.geometry_hash} "
            f"actual={actual_hash}"
        )
    return summary, design, config, proposal.geometry


def build_air_variant(source: Geometry) -> tuple[Geometry, AirVariantDefinition]:
    """Replace FR4 with lossless air while preserving all conductor dimensions."""

    metadata = source.metadata
    required = {
        "length",
        "width",
        "substrate_thickness",
        "substrate_length",
        "substrate_width",
        "eps_r",
        "feed_x",
    }
    missing = sorted(required - metadata.keys())
    if missing:
        raise CrossCheckError(f"source patch metadata lacks {missing}")
    length = float(metadata["length"])
    width = float(metadata["width"])
    ground_length = float(metadata["substrate_length"])
    ground_width = float(metadata["substrate_width"])
    gap = float(metadata["substrate_thickness"])
    feed_x = float(metadata["feed_x"])
    definition = AirVariantDefinition(
        patch_length_m=length,
        patch_width_m=width,
        patch_metal_area_m2=length * width,
        ground_length_m=ground_length,
        ground_width_m=ground_width,
        ground_metal_area_m2=ground_length * ground_width,
        air_gap_m=gap,
        feed_x_m=feed_x,
        feed_y_m=0.0,
        original_eps_r=float(metadata["eps_r"]),
    )
    variant = ParametricGenerator().rectangular_patch(
        width=width,
        length=length,
        substrate_thickness=gap,
        substrate_width=ground_width,
        substrate_length=ground_length,
        eps_r=1.0,
        loss_tangent=0.0,
        feed_x=feed_x,
    )
    variant.name = "crosscheck_air_variant"
    variant.metadata["cross_check_protocol"] = PROTOCOL_VERSION
    return variant, definition


def _axis_nodes(low: float, high: float, extra: float) -> tuple[float, ...]:
    if not low < extra < high:
        return tuple(
            float(value) for value in np.linspace(low, high, GRID_INTERVALS + 1)
        )
    fraction_left = (extra - low) / (high - low)
    left_intervals = min(
        max(round(GRID_INTERVALS * fraction_left), 1),
        GRID_INTERVALS - 1,
    )
    right_intervals = GRID_INTERVALS - left_intervals
    left = [
        float(value) for value in np.linspace(low, extra, left_intervals + 1)
    ]
    right = [
        float(value) for value in np.linspace(extra, high, right_intervals + 1)
    ]
    return (*left, *right[1:])


def _plane_edges(
    *,
    length: float,
    width: float,
    z: float,
    feed_x: float,
    radius: float,
    first_tag: int,
) -> tuple[list[WireSegment], int, float]:
    x_nodes = _axis_nodes(-length / 2.0, length / 2.0, feed_x)
    y_nodes = _axis_nodes(-width / 2.0, width / 2.0, 0.0)
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
    definition: AirVariantDefinition,
) -> tuple[tuple[WireSegment, ...], WireGridDefinition]:
    """Create explicit finite patch/ground grids using an equal-area radius."""

    patch_x = _axis_nodes(
        -definition.patch_length_m / 2.0,
        definition.patch_length_m / 2.0,
        definition.feed_x_m,
    )
    patch_y = _axis_nodes(
        -definition.patch_width_m / 2.0,
        definition.patch_width_m / 2.0,
        definition.feed_y_m,
    )
    ground_x = _axis_nodes(
        -definition.ground_length_m / 2.0,
        definition.ground_length_m / 2.0,
        definition.feed_x_m,
    )
    ground_y = _axis_nodes(
        -definition.ground_width_m / 2.0,
        definition.ground_width_m / 2.0,
        definition.feed_y_m,
    )
    total_length = (
        len(patch_y) * definition.patch_length_m
        + len(patch_x) * definition.patch_width_m
        + len(ground_y) * definition.ground_length_m
        + len(ground_x) * definition.ground_width_m
    )
    metal_area = (
        definition.patch_metal_area_m2 + definition.ground_metal_area_m2
    )
    radius = metal_area / (2.0 * math.pi * total_length)
    feed_radius = min(radius, definition.air_gap_m / 20.0)
    feed = WireSegment(
        tag=1,
        start_m=(definition.feed_x_m, definition.feed_y_m, 0.0),
        stop_m=(
            definition.feed_x_m,
            definition.feed_y_m,
            definition.air_gap_m,
        ),
        radius_m=feed_radius,
    )
    patch, next_tag, patch_length = _plane_edges(
        length=definition.patch_length_m,
        width=definition.patch_width_m,
        z=definition.air_gap_m,
        feed_x=definition.feed_x_m,
        radius=radius,
        first_tag=2,
    )
    ground, _, ground_length = _plane_edges(
        length=definition.ground_length_m,
        width=definition.ground_width_m,
        z=0.0,
        feed_x=definition.feed_x_m,
        radius=radius,
        first_tag=next_tag,
    )
    wires = (feed, *patch, *ground)
    grid = WireGridDefinition(
        grid_intervals=GRID_INTERVALS,
        wire_count=len(wires),
        grid_wire_count=len(patch) + len(ground),
        total_grid_wire_length_m=patch_length + ground_length,
        represented_metal_area_m2=metal_area,
        equal_area_wire_radius_m=radius,
        feed_wire_radius_m=feed_radius,
    )
    return wires, grid


def evaluate_cross_check(
    openems_resonance_hz: float,
    openems_s11_db: float,
    nec2_resonance_hz: float,
    nec2_s11_db: float,
) -> CrossCheckDecision:
    """Apply the frozen 5% resonance and 3 dB depth thresholds inclusively."""

    frequency_difference = abs(nec2_resonance_hz - openems_resonance_hz) / (
        openems_resonance_hz
    )
    s11_difference = abs(nec2_s11_db - openems_s11_db)
    frequency_ok = frequency_difference <= MAX_RESONANCE_RELATIVE_DIFFERENCE
    s11_ok = s11_difference <= MAX_S11_DEPTH_DIFFERENCE_DB
    return CrossCheckDecision(
        resonance_relative_difference=frequency_difference,
        resonance_threshold_met=frequency_ok,
        s11_depth_difference_db=s11_difference,
        s11_depth_threshold_met=s11_ok,
        verdict="CONFIRMED" if frequency_ok and s11_ok else "DIVERGENT",
    )


def _curve(result: SimulationResult) -> SolverCurve:
    if result.s_params is None or not result.s_params.s_matrix:
        raise CrossCheckError(f"{result.solver_name} returned no S11 curve")
    frequencies = tuple(float(item) for item in result.s_params.frequency)
    s11_db = tuple(
        20.0 * math.log10(max(abs(row[0][0]), 1e-15))
        for row in result.s_params.s_matrix
    )
    index = min(range(len(s11_db)), key=s11_db.__getitem__)
    return SolverCurve(
        solver_name=result.solver_name,
        solver_mode=str(result.solver_metadata.get("solver_mode", "unknown")),
        frequency_hz=frequencies,
        s11_db=s11_db,
        resonance_frequency_hz=frequencies[index],
        resonance_s11_db=s11_db[index],
        simulation_time_seconds=result.simulation_time_sec,
    )


def _nec_deck(
    wires: tuple[WireSegment, ...],
    frequency_range: tuple[float, float],
) -> NEC2CardWriter:
    writer = NEC2CardWriter(title=f"YAF {PROTOCOL_VERSION}")
    for wire in wires:
        writer.cards.append(
            writer.gw_card(
                wire.tag,
                1,
                *wire.start_m,
                *wire.stop_m,
                wire.radius_m,
            )
        )
    writer.cards.append(writer.ge_card(0))
    writer.cards.append(writer.ex_card(excitation_type=0, tag=1, segment=1))
    writer.cards.append(
        writer.fr_card(
            (
                frequency_range[0] / 1e6,
                frequency_range[1] / 1e6,
                FREQUENCY_POINTS,
            )
        )
    )
    writer.cards.append(
        writer.rp_card(n_theta=3, n_phi=1, dtheta=90.0, dphi=0.0)
    )
    return writer


def _run_nec2(
    wires: tuple[WireSegment, ...],
    spec: SimulationSpec,
    *,
    temporary_root: Path,
) -> SimulationResult:
    adapter = NEC2Adapter()
    runner = adapter._resolve_runner()
    if runner is None:
        raise CrossCheckError("real nec2c is unavailable through PATH or WSL")
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yc_", dir=temporary_root) as directory:
        root = Path(directory)
        input_path = root / "crosscheck.nec"
        output_path = root / "crosscheck.out"
        input_path.write_bytes(_nec_deck(wires, spec.frequency_range).to_bytes())
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
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CrossCheckError(f"nec2c execution failed: {error}") from error
        elapsed = time.monotonic() - started
        if process.returncode != 0 or not output_path.is_file():
            stderr = process.stderr.decode("utf-8", errors="replace")[-500:]
            raise CrossCheckError(
                f"nec2c exited with {process.returncode}: {stderr}"
            )
        try:
            result = adapter._parse_nec_output(
                output_path,
                spec,
                str(uuid.uuid4()),
                elapsed,
            )
        except Exception as error:
            output_tail = output_path.read_text(errors="replace")[-1200:]
            raise CrossCheckError(
                f"nec2c output is unusable: {error}; output_tail={output_tail}"
            ) from error
        result.solver_metadata["runner"] = " ".join(runner)
        result.solver_metadata["cross_check_protocol"] = PROTOCOL_VERSION
        return result


def _spec_name(config: ExplorationConfig) -> str:
    prefix = config.spec.name.split("_", maxsplit=1)[0]
    if prefix not in {"wifi24", "wifi58", "n78"}:
        raise CrossCheckError(f"cannot infer registered spec from {config.spec.name!r}")
    return prefix


def _load_cross_state(path: Path, batch_id: str) -> CrossCheckState:
    if not path.is_file():
        return CrossCheckState(batch_id=batch_id)
    try:
        state = CrossCheckState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"invalid cross-check state: {error}") from error
    if state.batch_id != batch_id:
        raise CrossCheckError("cross-check state belongs to another batch")
    return state


def record_cross_check_failure(
    source_run_id: str,
    design_index: int,
    error: str,
    *,
    batch_id: str,
    repo_root: Path,
) -> CrossCheckFailureRecord:
    """Durably retain a failed attempt that produced no numeric verdict."""

    state_path = repo_root / "runs" / f"crosscheck_{batch_id}" / "state.json"
    state = _load_cross_state(state_path, batch_id)
    failure = CrossCheckFailureRecord(
        source_run_id=source_run_id,
        source_design_index=design_index,
        timestamp=datetime.now(UTC),
        error=error,
    )
    state = state.model_copy(
        update={"failed_attempts": (*state.failed_attempts, failure)}
    )
    _write_json_lf(state_path, state.model_dump(mode="json"))
    return failure


async def run_cross_check(
    source_run_id: str,
    *,
    design_index: int,
    batch_id: str,
    repo_root: Path,
) -> CrossCheckRunSummary:
    """Run and persist one real openEMS/NEC2 comparison from archived inputs."""

    archived, design, config, source_geometry = reconstruct_archived_design(
        source_run_id,
        design_index,
        artifacts_root=repo_root / "artifacts" / "runs",
    )
    spec_name = _spec_name(config)
    run_id = f"{batch_id}-{spec_name}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"cross-check run directory already exists: {run_id}")
    started_at = datetime.now(UTC)
    air_geometry, air_definition = build_air_variant(source_geometry)
    wires, grid_definition = build_wire_grid(air_definition)

    estimate = C0 / (2.0 * air_definition.patch_length_m)
    frequency_range = (0.75 * estimate, 1.25 * estimate)
    simulation_spec = SimulationSpec(
        name=run_id,
        frequency_range=frequency_range,
        frequency_points=FREQUENCY_POINTS,
        far_field_request=None,
    )
    openems_adapter = OpenEMSAdapter()
    mesh = await openems_adapter.mesh(air_geometry, simulation_spec)
    openems_result = await openems_adapter.solve(mesh, simulation_spec)
    openems_curve = _curve(openems_result)
    if openems_curve.solver_mode not in {"subprocess", "native"}:
        raise CrossCheckError(
            f"openEMS cross-check is not real: mode={openems_curve.solver_mode}"
        )
    nec2_result = _run_nec2(
        wires,
        simulation_spec,
        temporary_root=repo_root / "tmp",
    )
    nec2_curve = _curve(nec2_result)
    if nec2_curve.solver_mode != "subprocess":
        raise CrossCheckError(
            f"NEC2 cross-check is not real: mode={nec2_curve.solver_mode}"
        )
    decision = evaluate_cross_check(
        openems_curve.resonance_frequency_hz,
        openems_curve.resonance_s11_db,
        nec2_curve.resonance_frequency_hz,
        nec2_curve.resonance_s11_db,
    )
    frozen_config = {
        "protocol_version": PROTOCOL_VERSION,
        "source_run_id": source_run_id,
        "source_design_index": design_index,
        "source_geometry_hash": design.geometry_hash,
        "source_run_config_hash": archived.config_hash,
        "frequency_range_hz": frequency_range,
        "frequency_points": FREQUENCY_POINTS,
        "grid_intervals": GRID_INTERVALS,
        "resonance_relative_threshold": MAX_RESONANCE_RELATIVE_DIFFERENCE,
        "s11_depth_threshold_db": MAX_S11_DEPTH_DIFFERENCE_DB,
        "air_variant": air_definition.model_dump(mode="json"),
        "wire_grid": grid_definition.model_dump(mode="json"),
    }
    config_hash = _canonical_hash(frozen_config)
    records = [
        CrossCheckLogRecord(
            run_id=run_id,
            source_run_id=source_run_id,
            source_design_index=design_index,
            source_geometry_hash=design.geometry_hash,
            spec_name=spec_name,
            timestamp=datetime.now(UTC),
            air_variant=air_definition,
            wire_grid=grid_definition,
            curve=curve,
        )
        for curve in (openems_curve, nec2_curve)
    ]
    summary = CrossCheckRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=archived.seed,
        config_hash=config_hash,
        config=frozen_config,
        solver_mode_counts={"subprocess": 2},
        source_run_id=source_run_id,
        source_design_index=design_index,
        source_geometry_hash=design.geometry_hash,
        spec_name=spec_name,
        air_variant=air_definition,
        wire_grid=grid_definition,
        openems=openems_curve,
        nec2=nec2_curve,
        decision=decision,
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    log_payload = "".join(
        json.dumps(
            record.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
        for record in records
    )
    (run_directory / "log.jsonl").write_bytes(log_payload.encode("utf-8"))
    _write_json_lf(
        run_directory / "summary.json",
        summary.model_dump(mode="json"),
    )

    state_path = repo_root / "runs" / f"crosscheck_{batch_id}" / "state.json"
    state = _load_cross_state(state_path, batch_id)
    if any(item.run_id == run_id for item in state.runs):
        raise CrossCheckError(f"cross-check state already contains {run_id}")
    state = state.model_copy(
        update={
            "runs": (
                *state.runs,
                CrossCheckStateRecord(
                    run_id=run_id,
                    source_run_id=source_run_id,
                    spec_name=spec_name,
                    verdict=decision.verdict,
                ),
            )
        }
    )
    _write_json_lf(state_path, state.model_dump(mode="json"))
    return summary


def _crosscheck_report(summary: CrossCheckAnalysisSummary) -> str:
    lines = [
        "# Day 3 cross-solver verification",
        "",
        "## Scope",
        "",
        (
            "Each comparison transforms one archived Day 2 GP design into the "
            "preregistered air-substrate variant, then compares real openEMS EC-FDTD "
            "with a real NEC2 finite wire-grid MoM model. This validates only the air "
            "variant; it does not directly validate the original FR4 substrate model."
        ),
        "",
        "| Spec | openEMS f_res | NEC2 f_res | delta f | S11 depth delta | Cross-check | Day 2 verdict | Sources |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for item in summary.decisions:
        lines.append(
            f"| {item.spec} | {item.openems_resonance_frequency_hz / 1e9:.6f} GHz "
            f"({item.openems_resonance_s11_db:.3f} dB) | "
            f"{item.nec2_resonance_frequency_hz / 1e9:.6f} GHz "
            f"({item.nec2_resonance_s11_db:.3f} dB) | "
            f"{item.resonance_relative_difference:.2%} | "
            f"{item.s11_depth_difference_db:.3f} dB | "
            f"{item.cross_solver_verdict} | {item.verdict} | "
            f"{', '.join(f'`{source}`' for source in item.source_run_ids)} |"
        )
    lines.extend(["", "## Interpretation", ""])
    for item in summary.decisions:
        lines.append(f"- **{item.spec}:** {item.reason}")
    lines.extend(
        [
            "",
            (
                "A CONFIRMED row means only that GP found a design better than the "
                "classic reference and that the preregistered air-variant cross-solver "
                "check agreed. It is not a claim that a new antenna was invented."
            ),
            "",
        ]
    )
    if summary.failed_attempts:
        lines.extend(["## Pre-decision failed attempts", ""])
        for attempt in summary.failed_attempts:
            display_error = attempt.error.split("; output_tail=", maxsplit=1)[0]
            if "no FREQUENCY block" in display_error:
                display_error = (
                    "nec2c produced no parseable FREQUENCY blocks before the "
                    "execution-card fix"
                )
            lines.append(
                f"- `{attempt.source_run_id}` design index "
                f"{attempt.source_design_index}: {display_error} "
                "(no numeric decision; thresholds were not applied)."
            )
        lines.append("")
    return "\n".join(lines)


def analyze_cross_checks(
    batch_id: str,
    *,
    repo_root: Path,
) -> CrossCheckAnalysisSummary:
    """Reevaluate Day 2 decisions from the completed cross-check evidence."""

    state_path = repo_root / "runs" / f"crosscheck_{batch_id}" / "state.json"
    state = _load_cross_state(state_path, batch_id)
    try:
        day2_payload = json.loads(
            (repo_root / "artifacts" / "analysis" / "day2" / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        day2_decisions = {
            str(item["spec"]): item for item in day2_payload["discovery_decisions"]
        }
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot read Day 2 analysis: {error}") from error
    decisions: list[CrossCheckDiscoveryDecision] = []
    for state_record in sorted(state.runs, key=lambda item: item.spec_name):
        try:
            run = CrossCheckRunSummary.model_validate_json(
                (repo_root / "runs" / state_record.run_id / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            day2 = day2_decisions[state_record.spec_name]
            improvement = float(day2["gp_vs_classic_improvement_fraction"])
            improvement_met = bool(day2["improvement_threshold_met"])
            day2_sources = tuple(str(item) for item in day2["source_run_ids"])
        except (OSError, KeyError, TypeError, ValidationError, ValueError) as error:
            raise CrossCheckError(
                f"cannot analyze {state_record.run_id}: {error}"
            ) from error
        confirmed = run.decision.verdict == "CONFIRMED" and improvement_met
        verdict: Literal["confirmed_improvement", "insufficient_evidence"] = (
            "confirmed_improvement" if confirmed else "insufficient_evidence"
        )
        if confirmed:
            reason = (
                "GP exceeded the frozen classic-improvement threshold and the "
                "air-variant solvers met both preregistered agreement thresholds."
            )
        else:
            reason = (
                "The air-variant cross-solver result is DIVERGENT (or the Day 2 "
                "improvement threshold was not met), so the positive verdict remains "
                "insufficient_evidence; the disagreement is retained as an anomaly signal."
            )
        decisions.append(
            CrossCheckDiscoveryDecision(
                spec=state_record.spec_name,
                cross_check_run_id=state_record.run_id,
                cross_solver_verdict=run.decision.verdict,
                openems_resonance_frequency_hz=(
                    run.openems.resonance_frequency_hz
                ),
                openems_resonance_s11_db=run.openems.resonance_s11_db,
                nec2_resonance_frequency_hz=run.nec2.resonance_frequency_hz,
                nec2_resonance_s11_db=run.nec2.resonance_s11_db,
                resonance_relative_difference=(
                    run.decision.resonance_relative_difference
                ),
                s11_depth_difference_db=run.decision.s11_depth_difference_db,
                day2_improvement_fraction=improvement,
                day2_improvement_threshold_met=improvement_met,
                verdict=verdict,
                reason=reason,
                source_run_ids=(*day2_sources, state_record.run_id),
            )
        )
    summary = CrossCheckAnalysisSummary(
        batch_id=batch_id,
        decisions=tuple(decisions),
        failed_attempts=state.failed_attempts,
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
    _write_text_lf(output / "report.md", _crosscheck_report(summary))
    return summary
