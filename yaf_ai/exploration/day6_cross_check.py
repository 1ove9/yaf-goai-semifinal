"""Frozen selection and native dual-band cross-check for Day 6."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.day6 import (
    DAY6_BATCH_ID,
    Day6BatchConfigDocument,
)
from yaf_ai.exploration.environment import geometry_hash
from yaf_ai.exploration.freeform_wire import (
    FREEFORM_FREQUENCY_POINTS,
    FREEFORM_SWEEP_HZ,
    HIGH_BAND_HZ,
    LOW_BAND_HZ,
    build_freeform_wire,
)
from yaf_ai.exploration.logger import AuditStepRecord
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

DAY6_PROTOCOL_VERSION = "day6-dual-band-v2.1"
DAY6_SELECTION_FILE = "artifacts/analysis/day6-freeform/selection.json"
DAY6_EDGE_GUARD = 3
DAY6_DEPTH_THRESHOLD_DB = -6.0
DAY6_GAP_THRESHOLD = 0.05
DAY6_PEARSON_THRESHOLD = 0.8
DAY6_OPENEMS_CONVERGENCE_THRESHOLD = 0.03
DAY6_OPENEMS_MAX_REFINEMENT_SECONDS = 30.0 * 60.0
DAY6_NEC2_FINAL_DENSITY = 160

Day6CrossCheckVerdict = Literal[
    "CONFIRMED", "DIVERGENT", "NO_RESONANCE_IN_BAND"
]


class SelectedDay6Design(BaseModel):
    """One immutable source address selected before cross-check output exists."""

    model_config = ConfigDict(frozen=True)

    rank: int = Field(gt=0)
    source_run_id: str
    source_step_index: int = Field(ge=0)
    source_geometry_hash: str
    source_config_hash: str
    source_score: float
    proposal_parameters: dict[str, float]
    proposer: str
    ocfd_run_id: str
    ocfd_score: float
    oracle_improvement_fraction: float


class Day6SelectionDocument(BaseModel):
    """Committed top-two result of the preregistered source-only selector."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str = DAY6_BATCH_ID
    selected_at: datetime
    selection_rule: str
    config_hash: str
    candidates: tuple[SelectedDay6Design, SelectedDay6Design]


class BandResonanceValidity(BaseModel):
    """One target-band local-minimum and depth gate for one solver."""

    model_config = ConfigDict(frozen=True)

    band_hz: tuple[float, float]
    minimum_index: int = Field(ge=0)
    minimum_frequency_hz: float = Field(gt=0.0)
    minimum_s11_db: float
    local_minimum: bool
    wide_sweep_interior: bool
    depth_threshold_db: float = DAY6_DEPTH_THRESHOLD_DB
    depth_threshold_met: bool
    valid: bool


class Day6BandDecision(BaseModel):
    """Two-solver agreement result for one target band."""

    model_config = ConfigDict(frozen=True)

    band_name: Literal["2.4_GHz", "5.8_GHz"]
    openems: BandResonanceValidity
    nec2: BandResonanceValidity
    resonance_relative_difference: float | None = Field(default=None, ge=0.0)
    resonance_threshold: float = DAY6_GAP_THRESHOLD
    resonance_threshold_met: bool | None = None
    s11_depth_difference_db: float | None = Field(default=None, ge=0.0)


class Day6CrossCheckDecision(BaseModel):
    """Mechanical application of the preregistered dual-band gates."""

    model_config = ConfigDict(frozen=True)

    protocol_version: str = DAY6_PROTOCOL_VERSION
    low_band: Day6BandDecision
    high_band: Day6BandDecision
    whole_sweep_pearson: float | None = Field(default=None, ge=-1.0, le=1.0)
    pearson_threshold: float = DAY6_PEARSON_THRESHOLD
    pearson_threshold_met: bool | None = None
    verdict: Day6CrossCheckVerdict


class Day6InstrumentRunSummary(BaseModel):
    """Archive-compatible real-solver result for one frozen candidate."""

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
    selected_design: SelectedDay6Design
    curve: SolverCurve


class Day6CrossCheckRunSummary(BaseModel):
    """Archive-compatible final two-solver decision for one candidate."""

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
    selected_design: SelectedDay6Design
    nec2: SolverCurve
    openems: SolverCurve
    decision: Day6CrossCheckDecision
    reference_gate_met: bool
    discovery_verdict: Literal["confirmed_improvement", "insufficient_evidence"]


class Day6FailureRunSummary(BaseModel):
    """Archive-compatible record of a solver failure with no numeric verdict."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 0
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int] = {}
    selected_design: SelectedDay6Design
    status: Literal["failed"] = "failed"
    failure_type: Literal["instrument_timeout"] = "instrument_timeout"
    failure: str
    result_status: Literal["no_numeric_decision"] = "no_numeric_decision"


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


def _write_run(
    run_directory: Path,
    summary: Day6InstrumentRunSummary | Day6CrossCheckRunSummary,
    curves: Sequence[tuple[str, SolverCurve]],
) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    records = [
        {
            "schema_version": 1,
            "event_type": "day6_cross_solver_result",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "protocol_version": DAY6_PROTOCOL_VERSION,
            "source_run_id": summary.selected_design.source_run_id,
            "source_step_index": summary.selected_design.source_step_index,
            "instrument": instrument,
            "curve": curve.model_dump(mode="json"),
        }
        for instrument, curve in curves
    ]
    payload = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
        for record in records
    )
    (run_directory / "log.jsonl").write_bytes(payload.encode("utf-8"))
    _write_json(run_directory / "summary.json", summary.model_dump(mode="json"))


def record_day6_timeout_failure(repo_root: Path) -> Day6FailureRunSummary:
    """Record the observed 300-second lambda/160 timeout before its retry."""

    selected = load_day6_selection(repo_root).candidates[0]
    _geometry, seed = reconstruct_day6_design(repo_root, selected)
    run_id = "day6-freeform-final-crosscheck-top1-timeout300"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        return Day6FailureRunSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    timestamp = datetime.now(UTC)
    config: dict[str, Any] = {
        "protocol_version": DAY6_PROTOCOL_VERSION,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "solver": "nec2",
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        "nec2_segments_per_wavelength": DAY6_NEC2_FINAL_DENSITY,
        "nec2_timeout_seconds": 300.0,
        "retry_changes_only_timeout_seconds_to": 1800.0,
    }
    summary = Day6FailureRunSummary(
        run_id=run_id,
        started_at=timestamp,
        finished_at=timestamp,
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        selected_design=selected,
        failure=(
            "subprocess.TimeoutExpired: real nec2c lambda/160 run exceeded 300 seconds; "
            "YAF_NO_FALLBACK=1 refused analytical fallback"
        ),
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "event_type": "day6_solver_failure",
        "run_id": run_id,
        "timestamp": timestamp.isoformat(),
        "protocol_version": DAY6_PROTOCOL_VERSION,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "failure_type": summary.failure_type,
        "failure": summary.failure,
        "result_status": summary.result_status,
    }
    (run_directory / "log.jsonl").write_bytes(
        (
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n"
        ).encode("utf-8")
    )
    _write_json(run_directory / "summary.json", summary.model_dump(mode="json"))
    return summary


def _load_evaluations(path: Path) -> tuple[AuditStepRecord, ...]:
    records: list[AuditStepRecord] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            if raw.get("event_type") == "evaluation":
                records.append(AuditStepRecord.model_validate(raw))
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CrossCheckError(f"cannot load Day 6 evidence {path}: {error}") from error
    return tuple(records)


def rank_unique_records(
    records: Sequence[AuditStepRecord], count: int = 2
) -> tuple[AuditStepRecord, ...]:
    """Apply score/run/step ordering and geometry-hash deduplication."""

    ordered = sorted(
        records,
        key=lambda record: (-record.score, record.run_id, record.step_index),
    )
    selected: list[AuditStepRecord] = []
    hashes: set[str] = set()
    for record in ordered:
        if record.geometry_hash in hashes:
            continue
        hashes.add(record.geometry_hash)
        selected.append(record)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise CrossCheckError(
            f"Day 6 selector found {len(selected)} unique records, expected {count}"
        )
    return tuple(selected)


def select_day6_designs(repo_root: Path) -> Day6SelectionDocument:
    """Select the frozen GP top two from complete archived batch evidence."""

    try:
        config_document = Day6BatchConfigDocument.model_validate_json(
            (
                repo_root
                / "artifacts"
                / "analysis"
                / "day6-freeform"
                / "batch-config.json"
            ).read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise CrossCheckError(f"cannot load archived Day 6 config: {error}") from error
    records: list[AuditStepRecord] = []
    for seed in config_document.config.seeds:
        run_id = f"day6-freeform-dual-gp-s{seed}"
        records.extend(
            _load_evaluations(repo_root / "artifacts" / "runs" / run_id / "log.jsonl")
        )
    expected = config_document.config.budget * len(config_document.config.seeds)
    if len(records) != expected:
        raise CrossCheckError(
            f"Day 6 GP evidence has {len(records)} evaluations, expected {expected}"
        )
    selected_records = rank_unique_records(records)
    candidates = tuple(
        SelectedDay6Design(
            rank=rank,
            source_run_id=record.run_id,
            source_step_index=record.step_index,
            source_geometry_hash=record.geometry_hash,
            source_config_hash=record.config_hash,
            source_score=record.score,
            proposal_parameters=record.proposal_parameters,
            proposer=record.proposer,
            ocfd_run_id=config_document.config.ocfd_run_id,
            ocfd_score=config_document.config.ocfd_score,
            oracle_improvement_fraction=(
                record.score / config_document.config.ocfd_score - 1.0
            ),
        )
        for rank, record in enumerate(selected_records, start=1)
    )
    return Day6SelectionDocument(
        selected_at=datetime.now(UTC),
        selection_rule=config_document.config.top_selection_rule,
        config_hash=config_document.config_hash,
        candidates=(candidates[0], candidates[1]),
    )


def write_day6_selection(repo_root: Path) -> Day6SelectionDocument:
    """Persist or integrity-check the source-only top-two selection."""

    path = repo_root / DAY6_SELECTION_FILE
    selected = select_day6_designs(repo_root)
    if path.is_file():
        existing = Day6SelectionDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if existing.model_copy(update={"selected_at": selected.selected_at}) != selected:
            raise CrossCheckError("committed Day 6 selection differs from source evidence")
        return existing
    _write_json(path, selected.model_dump(mode="json"))
    return selected


def load_day6_selection(repo_root: Path) -> Day6SelectionDocument:
    """Load and recompute the committed selection before any solver call."""

    path = repo_root / DAY6_SELECTION_FILE
    if not path.is_file():
        raise CrossCheckError("Day 6 selection must be committed before cross-check")
    stored = Day6SelectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    recomputed = select_day6_designs(repo_root)
    if stored.model_copy(update={"selected_at": recomputed.selected_at}) != recomputed:
        raise CrossCheckError("Day 6 selection no longer matches archived evidence")
    return stored


def reconstruct_day6_design(
    repo_root: Path, selected: SelectedDay6Design
) -> tuple[Geometry, int]:
    """Rebuild a selected N=7 geometry and verify its source hash."""

    summary_path = (
        repo_root / "artifacts" / "runs" / selected.source_run_id / "summary.json"
    )
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CrossCheckError(f"cannot load source summary: {error}") from error
    version = str(summary["config"]["proposal_space_version"])
    try:
        node_count = int(version.rsplit("-n", 1)[1])
    except (IndexError, ValueError) as error:
        raise CrossCheckError(f"cannot parse node count from {version}") from error
    geometry = build_freeform_wire(
        selected.proposal_parameters, node_count, selected.proposer
    )
    actual_hash = geometry_hash(geometry)
    if actual_hash != selected.source_geometry_hash:
        raise CrossCheckError(
            f"selected geometry hash mismatch expected={selected.source_geometry_hash} "
            f"actual={actual_hash}"
        )
    return geometry, int(summary["seed"])


def band_validity(
    curve: SolverCurve, band_hz: tuple[float, float]
) -> BandResonanceValidity:
    """Find a target-band local minimum and apply v2.1 global edge/depth gates."""

    indices = [
        index
        for index, frequency in enumerate(curve.frequency_hz)
        if band_hz[0] <= frequency <= band_hz[1]
    ]
    if not indices:
        raise ValueError("curve does not sample the requested target band")
    index = min(indices, key=curve.s11_db.__getitem__)
    interior = DAY6_EDGE_GUARD <= index <= len(curve.s11_db) - DAY6_EDGE_GUARD - 1
    local = (
        0 < index < len(curve.s11_db) - 1
        and curve.s11_db[index] <= curve.s11_db[index - 1]
        and curve.s11_db[index] <= curve.s11_db[index + 1]
        and (
            curve.s11_db[index] < curve.s11_db[index - 1]
            or curve.s11_db[index] < curve.s11_db[index + 1]
        )
    )
    depth_met = curve.s11_db[index] <= DAY6_DEPTH_THRESHOLD_DB
    return BandResonanceValidity(
        band_hz=band_hz,
        minimum_index=index,
        minimum_frequency_hz=curve.frequency_hz[index],
        minimum_s11_db=curve.s11_db[index],
        local_minimum=local,
        wide_sweep_interior=interior,
        depth_threshold_met=depth_met,
        valid=local and interior and depth_met,
    )


def _band_decision(
    name: Literal["2.4_GHz", "5.8_GHz"],
    band_hz: tuple[float, float],
    openems: SolverCurve,
    nec2: SolverCurve,
) -> Day6BandDecision:
    open_validity = band_validity(openems, band_hz)
    nec_validity = band_validity(nec2, band_hz)
    if not open_validity.valid or not nec_validity.valid:
        return Day6BandDecision(
            band_name=name, openems=open_validity, nec2=nec_validity
        )
    gap = abs(
        open_validity.minimum_frequency_hz - nec_validity.minimum_frequency_hz
    ) / open_validity.minimum_frequency_hz
    return Day6BandDecision(
        band_name=name,
        openems=open_validity,
        nec2=nec_validity,
        resonance_relative_difference=gap,
        resonance_threshold_met=gap <= DAY6_GAP_THRESHOLD,
        s11_depth_difference_db=abs(
            open_validity.minimum_s11_db - nec_validity.minimum_s11_db
        ),
    )


def _pearson(openems: SolverCurve, nec2: SolverCurve) -> float:
    common = np.asarray(openems.frequency_hz, dtype=float)
    left = np.asarray(openems.s11_db, dtype=float)
    right = np.interp(
        common,
        np.asarray(nec2.frequency_hz, dtype=float),
        np.asarray(nec2.s11_db, dtype=float),
    )
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def evaluate_day6_curves(
    openems: SolverCurve, nec2: SolverCurve
) -> Day6CrossCheckDecision:
    """Apply both band gates followed by full-sweep Pearson correlation."""

    low = _band_decision("2.4_GHz", LOW_BAND_HZ, openems, nec2)
    high = _band_decision("5.8_GHz", HIGH_BAND_HZ, openems, nec2)
    if not (
        low.openems.valid
        and low.nec2.valid
        and high.openems.valid
        and high.nec2.valid
    ):
        return Day6CrossCheckDecision(
            low_band=low, high_band=high, verdict="NO_RESONANCE_IN_BAND"
        )
    correlation = _pearson(openems, nec2)
    gaps_met = bool(
        low.resonance_threshold_met and high.resonance_threshold_met
    )
    correlation_met = correlation >= DAY6_PEARSON_THRESHOLD
    return Day6CrossCheckDecision(
        low_band=low,
        high_band=high,
        whole_sweep_pearson=correlation,
        pearson_threshold_met=correlation_met,
        verdict="CONFIRMED" if gaps_met and correlation_met else "DIVERGENT",
    )


def high_band_shift(first: SolverCurve, second: SolverCurve) -> float | None:
    """Return adjacent valid high-band resonance shift, or None if either is invalid."""

    first_validity = band_validity(first, HIGH_BAND_HZ)
    second_validity = band_validity(second, HIGH_BAND_HZ)
    if not first_validity.valid or not second_validity.valid:
        return None
    return abs(
        first_validity.minimum_frequency_hz - second_validity.minimum_frequency_hz
    ) / second_validity.minimum_frequency_hz


async def run_day6_instrument(
    repo_root: Path,
    selected: SelectedDay6Design,
    *,
    solver: Literal["nec2", "openems"],
    run_id: str,
    nec2_density: int = DAY6_NEC2_FINAL_DENSITY,
    openems_refinement: float = 1.0,
) -> Day6InstrumentRunSummary:
    """Execute and archive-ready record one real final-instrument curve."""

    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"Day 6 instrument run already exists: {run_id}")
    geometry, seed = reconstruct_day6_design(repo_root, selected)
    settings = {
        "nec2_segments_per_wavelength": nec2_density,
        "openems_mesh_refinement": openems_refinement,
    }
    spec = SimulationSpec(
        name=run_id,
        frequency_range=FREEFORM_SWEEP_HZ,
        frequency_points=FREEFORM_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings=settings,
    )
    adapter = NEC2Adapter() if solver == "nec2" else OpenEMSAdapter()
    started_at = datetime.now(UTC)
    mesh = await adapter.mesh(geometry, spec)
    curve = _curve(await adapter.solve(mesh, spec))
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"Day 6 {solver} result is not real: {curve.solver_mode}")
    config: dict[str, Any] = {
        "protocol_version": DAY6_PROTOCOL_VERSION,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "solver": solver,
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        **settings,
    }
    summary = Day6InstrumentRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 1},
        selected_design=selected,
        curve=curve,
    )
    _write_run(run_directory, summary, [(solver, curve)])
    return summary


async def run_day6_final_cross_check(
    repo_root: Path,
    selected: SelectedDay6Design,
    *,
    openems_refinement: float,
) -> Day6CrossCheckRunSummary:
    """Run both frozen final instruments and apply the unchanged gates."""

    run_id = f"day6-freeform-final-crosscheck-top{selected.rank}"
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        raise CrossCheckError(f"Day 6 final cross-check exists: {run_id}")
    geometry, seed = reconstruct_day6_design(repo_root, selected)
    settings = {
        "nec2_segments_per_wavelength": DAY6_NEC2_FINAL_DENSITY,
        "nec2_timeout_seconds": 1800.0,
        "openems_mesh_refinement": openems_refinement,
    }
    spec = SimulationSpec(
        name=run_id,
        frequency_range=FREEFORM_SWEEP_HZ,
        frequency_points=FREEFORM_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings=settings,
    )
    started_at = datetime.now(UTC)
    curves: dict[str, SolverCurve] = {}
    for solver, adapter in (("nec2", NEC2Adapter()), ("openems", OpenEMSAdapter())):
        mesh = await adapter.mesh(geometry, spec)
        curve = _curve(await adapter.solve(mesh, spec))
        if curve.solver_mode != "subprocess":
            raise CrossCheckError(
                f"Day 6 final {solver} result is not real: {curve.solver_mode}"
            )
        curves[solver] = curve
    decision = evaluate_day6_curves(curves["openems"], curves["nec2"])
    reference_met = selected.source_score >= 1.10 * selected.ocfd_score
    discovery = (
        "confirmed_improvement"
        if reference_met and decision.verdict == "CONFIRMED"
        else "insufficient_evidence"
    )
    config: dict[str, Any] = {
        "protocol_version": DAY6_PROTOCOL_VERSION,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        **settings,
    }
    summary = Day6CrossCheckRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 2},
        selected_design=selected,
        nec2=curves["nec2"],
        openems=curves["openems"],
        decision=decision,
        reference_gate_met=reference_met,
        discovery_verdict=discovery,
    )
    _write_run(
        run_directory,
        summary,
        [("nec2", curves["nec2"]), ("openems", curves["openems"])],
    )
    return summary


def openems_converged(first: SolverCurve, second: SolverCurve) -> bool:
    """Apply the frozen adjacent-mesh high-band self-convergence gate."""

    shift = high_band_shift(first, second)
    return shift is not None and shift <= DAY6_OPENEMS_CONVERGENCE_THRESHOLD


def finite_curve(curve: SolverCurve) -> bool:
    """Return whether every stored frequency and S11 sample is finite."""

    return all(math.isfinite(value) for value in (*curve.frequency_hz, *curve.s11_db))
