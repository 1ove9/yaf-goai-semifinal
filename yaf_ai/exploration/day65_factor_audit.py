"""Factorial anchor audit and terminal candidate-B execution for Day 6.5."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.day6_cross_check import (
    DAY6_GAP_THRESHOLD,
    DAY6_PEARSON_THRESHOLD,
    Day6InstrumentRunSummary,
    SelectedDay6Design,
    evaluate_day6_curves,
    reconstruct_day6_design,
)
from yaf_ai.exploration.day65 import (
    DAY65_DIPOLE_LENGTH_M,
    DAY65_FEED_GAP_M,
    DAY65_PROTOCOL_VERSION,
    DAY65_ROTATION_POINTS,
    DAY65_ROTATION_RUN_ID,
    DAY65_ROTATION_SWEEP_HZ,
    Day65RotationSummary,
    RotationResonance,
    build_rotation_dipole,
    rotation_resonance,
)
from yaf_ai.exploration.day65_diagnostics import (
    ANALYSIS_RELATIVE_DIRECTORY as PRIOR_DIAGNOSTIC_DIRECTORY,
)
from yaf_ai.exploration.day65_diagnostics import (
    BASELINE_OPENEMS_FREQUENCY_HZ,
    RADIUS_DIAGNOSTIC_RUN_ID,
    RadiusDiagnosticSummary,
)
from yaf_ai.exploration.day65_repair import (
    DAY65_OPENEMS_BASE_TIMESTEPS,
    DAY65_RELEASED_REFINEMENT,
    DAY65_REPAIR_PROTOCOL,
    BandVerdict,
    Day65CandidateRunSummary,
    _band_verdict,
    _canonical_hash,
    _load_source_nec2,
    _whole_sweep_pearson,
    _write_run,
    frozen_candidates,
)
from yaf_ai.exploration.freeform_wire import (
    FREEFORM_FREQUENCY_POINTS,
    FREEFORM_SWEEP_HZ,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.base import SolverError
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

PREREGISTRATION_COMMIT = "07a7b576e693e8da566bb287a92d5d3aca03af32"
ANALYSIS_RELATIVE_DIRECTORY = Path("artifacts/analysis/day65-factor-audit")
STATE_RELATIVE_DIRECTORY = Path("runs/day65-factor-audit")

SURROGATE_RADIUS_M = 0.00025
BASELINE_NEC2_THICK_FREQUENCY_HZ = 2.290e9
SHORTEN_EACH_END_M = 0.00025
SHORTENED_CENTERLINE_LENGTH_M = 0.060682134285714285
SENSITIVE_FEED_GAP_M = 0.0003
MATERIAL_SHIFT_HZ = 20.0e6
SEGMENT_STABILITY_HZ = 10.0e6
OPENEMS_BASE_REFINEMENT = 6.0
OPENEMS_FINE_REFINEMENT = 8.0
OPENEMS_BASE_TIMESTEPS = 40000
OPENEMS_TIMEOUT_SECONDS = 7200.0
CANDIDATE_B_TIMEOUT_SECONDS = 43200.0

F3_L80_RUN_ID = "day65-factor-f3-nec2-lambda80"
F3_L320_RUN_ID = "day65-factor-f3-nec2-lambda320"
F4_NEC2_RUN_ID = "day65-factor-f4-nec2-feed-gap-0p3mm"
F2_OPENEMS_RUN_ID = "day65-factor-f2-openems-endcap-shortened"
F4_OPENEMS_RUN_ID = "day65-factor-f4-openems-feed-gap-0p3mm"
F1_OPENEMS_RUN_ID = "day65-factor-f1-openems-8x"
CANDIDATE_B_OPENEMS_RUN_ID = "day65-repair-openems-convergence-top2-6x"
CANDIDATE_B_REVERDICT_RUN_ID = "day65-repair-crosscheck-top2"
CANDIDATE_B_REBOOT_FAILURE_RUN_ID = (
    "day65-repair-openems-convergence-top2-6x-host-reboot"
)
REBOOT_REPLACEMENT_PREREGISTRATION_COMMIT = "6b292f49f70f4f3bfcb2988c14dba995c5167962"
HOST_REBOOT_AT = datetime.fromisoformat("2026-08-13T15:07:29.500000+00:00")

FactorName = Literal["F1", "F2", "F3", "F4"]
SolverName = Literal["nec2", "openems"]
Materiality = Literal["material", "minor"]
SegmentationClassification = Literal[
    "segmentation_stable", "nec2_thick_wire_not_converged"
]
CandidateBStatus = Literal[
    "running", "success", "infeasible_at_current_compute"
]


class FactorRunSummary(BaseModel):
    """Archive-compatible result from one preregistered single-factor solve."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 1
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int]
    factor: FactorName
    solver: SolverName
    changed_variable: str
    reference_frequency_hz: float
    curve: SolverCurve
    resonance: RotationResonance
    delta_frequency_hz: float
    decision_shift_hz: float | None = None
    materiality: Materiality | None = None


class SegmentationDecision(BaseModel):
    """Frozen F3 interpretation against the lambda/160 thick-wire anchor."""

    model_config = ConfigDict(frozen=True)

    lambda80_frequency_hz: float
    lambda160_frequency_hz: float = BASELINE_NEC2_THICK_FREQUENCY_HZ
    lambda320_frequency_hz: float
    maximum_shift_hz: float
    threshold_hz: float = SEGMENT_STABILITY_HZ
    classification: SegmentationClassification


class CandidateBTerminalState(BaseModel):
    """Crash-visible state proving the single terminal retry was not repeated."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    status: CandidateBStatus
    started_at: datetime
    finished_at: datetime | None = None
    preregistration_commit: str = PREREGISTRATION_COMMIT
    run_id: str = CANDIDATE_B_OPENEMS_RUN_ID
    timeout_seconds: float = CANDIDATE_B_TIMEOUT_SECONDS
    source_run_id: str = "day6-freeform-dual-gp-s202"
    source_step_index: int = 172
    expected_xml_sha256: str
    observed_xml_sha256: str
    failure: str | None = None
    re_verdict_run_id: str | None = None
    dual_band_verdict: str | None = None
    discovery_verdict: str | None = None


class CandidateBInterruptionSummary(BaseModel):
    """Archive-compatible zero-result evidence for the external host reboot."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    run_id: str = CANDIDATE_B_REBOOT_FAILURE_RUN_ID
    started_at: datetime
    finished_at: datetime = HOST_REBOOT_AT
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 0
    evaluation_budget: int = 1
    solver_mode_counts: dict[str, int] = {}
    selected_design: SelectedDay6Design
    status: Literal["failed"] = "failed"
    failure_type: Literal["external_host_reboot"] = "external_host_reboot"
    failure: str
    result_status: Literal["no_numeric_result"] = "no_numeric_result"
    expected_xml_sha256: str
    observed_xml_sha256: str
    replacement_preregistration_commit: str = (
        REBOOT_REPLACEMENT_PREREGISTRATION_COMMIT
    )


class ResidualBiasEstimate(BaseModel):
    """One non-additive residual cross-solver frequency-bias estimate."""

    model_config = ConfigDict(frozen=True)

    basis: str
    nec2_frequency_hz: float
    openems_frequency_hz: float
    residual_hz: float


class Day65FactorAuditSummary(BaseModel):
    """Machine-readable final output of the preregistered audit."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    generated_at: datetime
    preregistration_commit: str = PREREGISTRATION_COMMIT
    baseline_nec2_thick_frequency_hz: float = BASELINE_NEC2_THICK_FREQUENCY_HZ
    baseline_openems_frequency_hz: float = BASELINE_OPENEMS_FREQUENCY_HZ
    factor_runs: tuple[FactorRunSummary, ...]
    segmentation: SegmentationDecision
    residual_bias_estimates: tuple[ResidualBiasEstimate, ...]
    candidate_b: CandidateBTerminalState
    correction_proposal_v2: tuple[str, ...]
    protocol_modified: Literal[False] = False
    es_random_started: Literal[False] = False


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
    os.replace(temporary, path)


@contextmanager
def _strict_solver_mode() -> Iterator[None]:
    previous = os.environ.get("YAF_NO_FALLBACK")
    os.environ["YAF_NO_FALLBACK"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("YAF_NO_FALLBACK", None)
        else:
            os.environ["YAF_NO_FALLBACK"] = previous


def classify_materiality(shift_hz: float) -> Materiality:
    """Apply the inclusive preregistered 20 MHz materiality boundary."""

    if not math.isfinite(shift_hz):
        raise ValueError("factor shift must be finite")
    return "material" if abs(shift_hz) >= MATERIAL_SHIFT_HZ else "minor"


def classify_segmentation_stability(
    lambda80_frequency_hz: float,
    lambda320_frequency_hz: float,
) -> SegmentationDecision:
    """Apply the inclusive 10 MHz F3 stability rule against lambda/160."""

    maximum = max(
        abs(lambda80_frequency_hz - BASELINE_NEC2_THICK_FREQUENCY_HZ),
        abs(lambda320_frequency_hz - BASELINE_NEC2_THICK_FREQUENCY_HZ),
    )
    classification: SegmentationClassification = (
        "segmentation_stable"
        if maximum <= SEGMENT_STABILITY_HZ
        else "nec2_thick_wire_not_converged"
    )
    return SegmentationDecision(
        lambda80_frequency_hz=lambda80_frequency_hz,
        lambda320_frequency_hz=lambda320_frequency_hz,
        maximum_shift_hz=maximum,
        classification=classification,
    )


def residual_bias(
    *,
    basis: str,
    nec2_frequency_hz: float,
    openems_frequency_hz: float,
) -> ResidualBiasEstimate:
    """Return one explicitly non-additive residual-bias estimate."""

    return ResidualBiasEstimate(
        basis=basis,
        nec2_frequency_hz=nec2_frequency_hz,
        openems_frequency_hz=openems_frequency_hz,
        residual_hz=abs(nec2_frequency_hz - openems_frequency_hz),
    )


def build_factor_anchor_geometry(
    *,
    feed_gap_m: float = DAY65_FEED_GAP_M,
    shorten_each_end_m: float = 0.0,
    wire_radius_m: float | None = None,
) -> Geometry:
    """Derive the y-axis r12 fixture with only named physical changes."""

    if feed_gap_m <= 0.0 or shorten_each_end_m < 0.0:
        raise ValueError("anchor dimensions must be non-negative and feed gap positive")
    if 2.0 * shorten_each_end_m >= DAY65_DIPOLE_LENGTH_M:
        raise ValueError("end shortening removes the dipole")
    base = build_rotation_dipole("y_axis")
    vertices = [list(vertex) for vertex in base.vertices]
    for index in (0, 3):
        vertices[index][0] = -feed_gap_m / 2.0
    for index in (1, 2):
        vertices[index][0] = feed_gap_m / 2.0
    vertices[2][1] -= shorten_each_end_m
    vertices[3][1] += shorten_each_end_m
    metadata = dict(base.metadata)
    metadata["feed_gap_m"] = feed_gap_m
    metadata["total_wire_length_m"] = DAY65_DIPOLE_LENGTH_M - (
        2.0 * shorten_each_end_m
    )
    metadata["control_positive"] = [vertices[1], vertices[2]]
    metadata["control_negative"] = [vertices[0], vertices[3]]
    if wire_radius_m is not None:
        if wire_radius_m <= 0.0:
            raise ValueError("wire radius must be positive")
        metadata["wire_radius_m"] = wire_radius_m
    return base.model_copy(update={"vertices": vertices, "metadata": metadata})


def _anchor_spec(
    *,
    nec2_density: int = 160,
    openems_refinement: float = OPENEMS_BASE_REFINEMENT,
) -> SimulationSpec:
    return SimulationSpec(
        name=DAY65_ROTATION_RUN_ID,
        frequency_range=DAY65_ROTATION_SWEEP_HZ,
        frequency_points=DAY65_ROTATION_POINTS,
        far_field_request=None,
        solver_settings={
            "openems_mesh_refinement": openems_refinement,
            "openems_base_timesteps": OPENEMS_BASE_TIMESTEPS,
            "openems_timeout_seconds": OPENEMS_TIMEOUT_SECONDS,
            "nec2_segments_per_wavelength": nec2_density,
            "nec2_timeout_seconds": 1800.0,
        },
    )


def _load_anchor_sources(repo_root: Path) -> tuple[Day65RotationSummary, RadiusDiagnosticSummary]:
    rotation = Day65RotationSummary.model_validate_json(
        (
            repo_root
            / "artifacts"
            / "runs"
            / DAY65_ROTATION_RUN_ID
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    radius = RadiusDiagnosticSummary.model_validate_json(
        (
            repo_root
            / "artifacts"
            / "runs"
            / RADIUS_DIAGNOSTIC_RUN_ID
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    y_axis = next(item for item in rotation.orientations if item.orientation == "y_axis")
    if (
        rotation.config.get("protocol_version") != DAY65_PROTOCOL_VERSION
        or y_axis.openems_resonance.frequency_hz != BASELINE_OPENEMS_FREQUENCY_HZ
        or radius.resonance.frequency_hz != BASELINE_NEC2_THICK_FREQUENCY_HZ
        or y_axis.openems.solver_mode != "subprocess"
        or radius.curve.solver_mode != "subprocess"
    ):
        raise CrossCheckError("archived Day 6.5 anchor sources changed")
    return rotation, radius


def _factor_config(
    *,
    factor: FactorName,
    solver: SolverName,
    changed_variable: str,
    settings: dict[str, float | int],
    geometry: Geometry,
) -> dict[str, Any]:
    return {
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "source_run_id": DAY65_ROTATION_RUN_ID,
        "source_orientation": "y_axis",
        "protocol_version": DAY65_PROTOCOL_VERSION,
        "factor": factor,
        "solver": solver,
        "changed_variable": changed_variable,
        "frequency_range_hz": DAY65_ROTATION_SWEEP_HZ,
        "frequency_points": DAY65_ROTATION_POINTS,
        "dipole_centerline_length_m": geometry.metadata["total_wire_length_m"],
        "feed_gap_m": geometry.metadata["feed_gap_m"],
        "wire_radius_m": geometry.metadata["wire_radius_m"],
        "openems_surrogate_radius_m": SURROGATE_RADIUS_M,
        **settings,
    }


def _write_factor_run(repo_root: Path, summary: FactorRunSummary) -> None:
    directory = repo_root / "runs" / summary.run_id
    if directory.exists():
        raise CrossCheckError(f"factor run already exists: {summary.run_id}")
    directory.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "event_type": "day65_factor_anchor_result",
        "run_id": summary.run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "factor": summary.factor,
        "solver": summary.solver,
        "changed_variable": summary.changed_variable,
        "curve": summary.curve.model_dump(mode="json"),
        "resonance": summary.resonance.model_dump(mode="json"),
        "delta_frequency_hz": summary.delta_frequency_hz,
        "decision_shift_hz": summary.decision_shift_hz,
        "materiality": summary.materiality,
    }
    (directory / "log.jsonl").write_bytes(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    _write_json(directory / "summary.json", summary.model_dump(mode="json"))


def load_factor_run(repo_root: Path, run_id: str) -> FactorRunSummary:
    """Load one completed local factor run without executing it again."""

    return FactorRunSummary.model_validate_json(
        (repo_root / "runs" / run_id / "summary.json").read_text(encoding="utf-8")
    )


async def run_nec2_factor(
    repo_root: Path,
    *,
    run_id: str,
    factor: Literal["F3", "F4"],
    density: int,
    feed_gap_m: float,
    changed_variable: str,
) -> FactorRunSummary:
    """Execute one real NEC2 single-factor anchor sweep."""

    _load_anchor_sources(repo_root)
    geometry = build_factor_anchor_geometry(
        feed_gap_m=feed_gap_m,
        wire_radius_m=SURROGATE_RADIUS_M,
    )
    settings: dict[str, float | int] = {
        "nec2_segments_per_wavelength": density,
        "nec2_timeout_seconds": 1800.0,
    }
    config = _factor_config(
        factor=factor,
        solver="nec2",
        changed_variable=changed_variable,
        settings=settings,
        geometry=geometry,
    )
    config_hash = _canonical_hash(config)
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        existing = load_factor_run(repo_root, run_id)
        if existing.config_hash != config_hash:
            raise CrossCheckError(f"existing factor config changed: {run_id}")
        return existing
    spec = _anchor_spec(nec2_density=density)
    adapter = NEC2Adapter()
    started_at = datetime.now(UTC)
    mesh = await adapter.mesh(geometry, spec)
    with _strict_solver_mode():
        curve = _curve(await adapter.solve(mesh, spec))
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"factor {run_id} is not real: {curve.solver_mode}")
    resonance = rotation_resonance(curve)
    summary = FactorRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=config_hash,
        config=config,
        solver_mode_counts={"subprocess": 1},
        factor=factor,
        solver="nec2",
        changed_variable=changed_variable,
        reference_frequency_hz=BASELINE_NEC2_THICK_FREQUENCY_HZ,
        curve=curve,
        resonance=resonance,
        delta_frequency_hz=resonance.frequency_hz - BASELINE_NEC2_THICK_FREQUENCY_HZ,
    )
    _write_factor_run(repo_root, summary)
    return summary


def _require_f3_stable(repo_root: Path) -> SegmentationDecision:
    lambda80 = load_factor_run(repo_root, F3_L80_RUN_ID)
    lambda320 = load_factor_run(repo_root, F3_L320_RUN_ID)
    decision = classify_segmentation_stability(
        lambda80.resonance.frequency_hz,
        lambda320.resonance.frequency_hz,
    )
    if decision.classification != "segmentation_stable":
        raise CrossCheckError("F3 thick-wire NEC2 segmentation is not stable")
    return decision


async def run_openems_factor(
    repo_root: Path,
    *,
    run_id: str,
    factor: Literal["F1", "F2", "F4"],
    refinement: float,
    feed_gap_m: float,
    shorten_each_end_m: float,
    changed_variable: str,
) -> FactorRunSummary:
    """Execute one real openEMS single-factor anchor sweep."""

    _load_anchor_sources(repo_root)
    _require_f3_stable(repo_root)
    load_factor_run(repo_root, F4_NEC2_RUN_ID)
    if factor in {"F1", "F4"}:
        load_factor_run(repo_root, F2_OPENEMS_RUN_ID)
    if factor == "F1":
        load_factor_run(repo_root, F4_OPENEMS_RUN_ID)
    geometry = build_factor_anchor_geometry(
        feed_gap_m=feed_gap_m,
        shorten_each_end_m=shorten_each_end_m,
    )
    settings: dict[str, float | int] = {
        "openems_mesh_refinement": refinement,
        "openems_base_timesteps": OPENEMS_BASE_TIMESTEPS,
        "openems_number_of_timesteps": int(round(OPENEMS_BASE_TIMESTEPS * refinement)),
        "openems_timeout_seconds": OPENEMS_TIMEOUT_SECONDS,
    }
    config = _factor_config(
        factor=factor,
        solver="openems",
        changed_variable=changed_variable,
        settings=settings,
        geometry=geometry,
    )
    config_hash = _canonical_hash(config)
    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        existing = load_factor_run(repo_root, run_id)
        if existing.config_hash != config_hash:
            raise CrossCheckError(f"existing factor config changed: {run_id}")
        return existing
    spec = _anchor_spec(openems_refinement=refinement)
    adapter = OpenEMSAdapter()
    started_at = datetime.now(UTC)
    mesh = await adapter.mesh(geometry, spec)
    with _strict_solver_mode():
        curve = _curve(await adapter.solve(mesh, spec))
    if curve.solver_mode != "subprocess":
        raise CrossCheckError(f"factor {run_id} is not real: {curve.solver_mode}")
    resonance = rotation_resonance(curve)
    delta = resonance.frequency_hz - BASELINE_OPENEMS_FREQUENCY_HZ
    decision_shift = abs(delta)
    if factor == "F4":
        nec2 = load_factor_run(repo_root, F4_NEC2_RUN_ID)
        decision_shift = abs(delta - nec2.delta_frequency_hz)
    summary = FactorRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=config_hash,
        config=config,
        solver_mode_counts={"subprocess": 1},
        factor=factor,
        solver="openems",
        changed_variable=changed_variable,
        reference_frequency_hz=BASELINE_OPENEMS_FREQUENCY_HZ,
        curve=curve,
        resonance=resonance,
        delta_frequency_hz=delta,
        decision_shift_hz=decision_shift,
        materiality=classify_materiality(decision_shift),
    )
    _write_factor_run(repo_root, summary)
    return summary


def _candidate_b_xml_hash(repo_root: Path) -> str:
    payload = json.loads(
        (
            repo_root
            / PRIOR_DIAGNOSTIC_DIRECTORY
            / "summary.json"
        ).read_text(encoding="utf-8")
    )
    value = str(payload["candidate_b"]["xml_sha256"])
    if len(value) != 64:
        raise CrossCheckError("prior candidate-B XML hash is invalid")
    return value


def _candidate_b_state_path(repo_root: Path) -> Path:
    return repo_root / STATE_RELATIVE_DIRECTORY / "candidate-b-terminal.json"


def _candidate_b_reboot_snapshot_path(repo_root: Path) -> Path:
    return repo_root / STATE_RELATIVE_DIRECTORY / "candidate-b-attempt1-host-reboot.json"


def _write_candidate_b_interruption_run(
    repo_root: Path,
    summary: CandidateBInterruptionSummary,
) -> None:
    directory = repo_root / "runs" / summary.run_id
    directory.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "event_type": "day65_candidate_b_external_interruption",
        "run_id": summary.run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "started_at": summary.started_at.isoformat(),
        "finished_at": summary.finished_at.isoformat(),
        "failure_type": summary.failure_type,
        "failure": summary.failure,
        "result_status": summary.result_status,
        "expected_xml_sha256": summary.expected_xml_sha256,
        "observed_xml_sha256": summary.observed_xml_sha256,
        "replacement_preregistration_commit": (
            summary.replacement_preregistration_commit
        ),
    }
    (directory / "log.jsonl").write_bytes(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    _write_json(directory / "summary.json", summary.model_dump(mode="json"))


def record_candidate_b_host_reboot(
    repo_root: Path,
) -> CandidateBInterruptionSummary:
    """Archive the zero-result interruption and re-arm one exact replacement."""

    load_factor_run(repo_root, F1_OPENEMS_RUN_ID)
    state_path = _candidate_b_state_path(repo_root)
    snapshot_path = _candidate_b_reboot_snapshot_path(repo_root)
    failure_directory = repo_root / "runs" / CANDIDATE_B_REBOOT_FAILURE_RUN_ID
    target_directory = repo_root / "runs" / CANDIDATE_B_OPENEMS_RUN_ID
    if target_directory.exists():
        raise CrossCheckError("candidate B produced a run; reboot re-arm is invalid")
    if snapshot_path.exists():
        raise CrossCheckError("candidate B host-reboot replacement was already re-armed")
    if not state_path.is_file():
        raise CrossCheckError("candidate B interrupted state is missing")
    state = CandidateBTerminalState.model_validate_json(
        state_path.read_text(encoding="utf-8")
    )
    expected_hash = _candidate_b_xml_hash(repo_root)
    if (
        state.status != "running"
        or state.run_id != CANDIDATE_B_OPENEMS_RUN_ID
        or state.timeout_seconds != CANDIDATE_B_TIMEOUT_SECONDS
        or state.expected_xml_sha256 != expected_hash
        or state.observed_xml_sha256 != expected_hash
        or state.finished_at is not None
    ):
        raise CrossCheckError("candidate B interrupted state changed")
    selected = frozen_candidates(repo_root)[1]
    _geometry, seed = reconstruct_day6_design(repo_root, selected)
    config: dict[str, Any] = {
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "replacement_preregistration_commit": (
            REBOOT_REPLACEMENT_PREREGISTRATION_COMMIT
        ),
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "target_run_id": CANDIDATE_B_OPENEMS_RUN_ID,
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        "openems_mesh_refinement": DAY65_RELEASED_REFINEMENT,
        "openems_base_timesteps": DAY65_OPENEMS_BASE_TIMESTEPS,
        "openems_number_of_timesteps": int(
            round(DAY65_OPENEMS_BASE_TIMESTEPS * DAY65_RELEASED_REFINEMENT)
        ),
        "openems_timeout_seconds": CANDIDATE_B_TIMEOUT_SECONDS,
        "xml_sha256": expected_hash,
        "host_reboot_at": HOST_REBOOT_AT.isoformat(),
    }
    summary = CandidateBInterruptionSummary(
        started_at=state.started_at,
        seed=seed,
        config_hash=_canonical_hash(config),
        config=config,
        selected_design=selected,
        failure=(
            "Host reboot externally terminated openEMS before a run directory or "
            "numeric result was produced."
        ),
        expected_xml_sha256=expected_hash,
        observed_xml_sha256=state.observed_xml_sha256,
    )
    if failure_directory.exists():
        existing = CandidateBInterruptionSummary.model_validate_json(
            (failure_directory / "summary.json").read_text(encoding="utf-8")
        )
        if existing != summary:
            raise CrossCheckError("candidate B reboot failure evidence changed")
    else:
        _write_candidate_b_interruption_run(repo_root, summary)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(state_path, snapshot_path)
    return summary


def _is_timeout_error(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, subprocess.TimeoutExpired):
            return True
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return False


def _candidate_b_settings() -> dict[str, float | int]:
    return {
        "openems_mesh_refinement": DAY65_RELEASED_REFINEMENT,
        "openems_base_timesteps": DAY65_OPENEMS_BASE_TIMESTEPS,
        "openems_timeout_seconds": CANDIDATE_B_TIMEOUT_SECONDS,
    }


def _load_candidate_b_run(repo_root: Path) -> Day6InstrumentRunSummary:
    return Day6InstrumentRunSummary.model_validate_json(
        (
            repo_root
            / "runs"
            / CANDIDATE_B_OPENEMS_RUN_ID
            / "summary.json"
        ).read_text(encoding="utf-8")
    )


def _write_candidate_b_instrument_run(
    repo_root: Path,
    summary: Day6InstrumentRunSummary,
) -> None:
    directory = repo_root / "runs" / summary.run_id
    if directory.exists():
        raise CrossCheckError(f"candidate B run already exists: {summary.run_id}")
    directory.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 1,
        "event_type": "day65_repaired_instrument_result",
        "run_id": summary.run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "protocol_version": DAY65_REPAIR_PROTOCOL,
        "source_run_id": summary.selected_design.source_run_id,
        "source_step_index": summary.selected_design.source_step_index,
        "instrument": "openems-6x-terminal-retry",
        "curve": summary.curve.model_dump(mode="json"),
    }
    (directory / "log.jsonl").write_bytes(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    _write_json(directory / "summary.json", summary.model_dump(mode="json"))


def _build_candidate_b_reverdict(
    repo_root: Path,
    selected: SelectedDay6Design,
    openems_run: Day6InstrumentRunSummary,
) -> Day65CandidateRunSummary:
    run_directory = repo_root / "runs" / CANDIDATE_B_REVERDICT_RUN_ID
    if run_directory.exists():
        return Day65CandidateRunSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    source_run_id, nec2, nec2_hash = _load_source_nec2(repo_root, selected)
    openems = openems_run.curve
    decision = evaluate_day6_curves(openems, nec2)
    pearson = _whole_sweep_pearson(openems, nec2)
    low = _band_verdict(decision, "low", pearson)
    high = _band_verdict(decision, "high", pearson)
    dual: BandVerdict
    if low == high == "CONFIRMED":
        dual = "CONFIRMED"
    elif low == "NO_RESONANCE_IN_BAND" or high == "NO_RESONANCE_IN_BAND":
        dual = "NO_RESONANCE_IN_BAND"
    else:
        dual = "DIVERGENT"
    reference_met = selected.source_score >= 1.10 * selected.ocfd_score
    discovery = (
        "confirmed_improvement"
        if dual == "CONFIRMED" and reference_met
        else "insufficient_evidence"
    )
    config: dict[str, Any] = {
        "protocol_version": DAY65_REPAIR_PROTOCOL,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "source_run_id": selected.source_run_id,
        "source_step_index": selected.source_step_index,
        "source_geometry_hash": selected.source_geometry_hash,
        "frequency_range_hz": FREEFORM_SWEEP_HZ,
        "frequency_points": FREEFORM_FREQUENCY_POINTS,
        "nec2_source_run_id": source_run_id,
        "nec2_curve_sha256": nec2_hash,
        "openems_curve_source_run_id": CANDIDATE_B_OPENEMS_RUN_ID,
        "nec2_segments_per_wavelength": 160,
        "resonance_relative_threshold": DAY6_GAP_THRESHOLD,
        "pearson_threshold": DAY6_PEARSON_THRESHOLD,
        **_candidate_b_settings(),
    }
    now = datetime.now(UTC)
    summary = Day65CandidateRunSummary(
        run_id=CANDIDATE_B_REVERDICT_RUN_ID,
        started_at=openems_run.started_at,
        finished_at=now,
        seed=openems_run.seed,
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 2},
        selected_design=selected,
        nec2_source_run_id=source_run_id,
        openems_curve_source_run_id=CANDIDATE_B_OPENEMS_RUN_ID,
        nec2_curve_sha256=nec2_hash,
        nec2=nec2,
        openems=openems,
        decision=decision,
        whole_sweep_pearson=pearson,
        low_band_verdict=low,
        high_band_verdict=high,
        dual_band_verdict=dual,
        discovery_verdict=discovery,
    )
    records = [
        {
            "schema_version": 1,
            "event_type": "day65_repaired_cross_solver_result",
            "run_id": summary.run_id,
            "timestamp": now.isoformat(),
            "protocol_version": DAY65_REPAIR_PROTOCOL,
            "source_run_id": selected.source_run_id,
            "source_step_index": selected.source_step_index,
            "instrument": "nec2-lambda160-archived",
            "instrument_source_run_id": source_run_id,
            "curve_sha256": nec2_hash,
            "curve": nec2.model_dump(mode="json"),
        },
        {
            "schema_version": 1,
            "event_type": "day65_repaired_cross_solver_result",
            "run_id": summary.run_id,
            "timestamp": now.isoformat(),
            "protocol_version": DAY65_REPAIR_PROTOCOL,
            "source_run_id": selected.source_run_id,
            "source_step_index": selected.source_step_index,
            "instrument": "openems-6x-repaired-terminal-retry",
            "instrument_source_run_id": CANDIDATE_B_OPENEMS_RUN_ID,
            "curve": openems.model_dump(mode="json"),
        },
    ]
    _write_run(run_directory, summary, records)
    return summary


async def run_candidate_b_terminal_retry(repo_root: Path) -> CandidateBTerminalState:
    """Execute at most one authorized candidate-B retry and frozen re-verdict."""

    load_factor_run(repo_root, F1_OPENEMS_RUN_ID)
    state_path = _candidate_b_state_path(repo_root)
    if state_path.exists():
        state = CandidateBTerminalState.model_validate_json(
            state_path.read_text(encoding="utf-8")
        )
        if state.status == "running":
            raise CrossCheckError(
                "candidate B already has a running/interrupted terminal attempt; "
                "refusing a second attempt"
            )
        return state
    selected = frozen_candidates(repo_root)[1]
    geometry, seed = reconstruct_day6_design(repo_root, selected)
    settings = _candidate_b_settings()
    spec = SimulationSpec(
        name=CANDIDATE_B_OPENEMS_RUN_ID,
        frequency_range=FREEFORM_SWEEP_HZ,
        frequency_points=FREEFORM_FREQUENCY_POINTS,
        far_field_request=None,
        solver_settings=settings,
    )
    adapter = OpenEMSAdapter()
    mesh = await adapter.mesh(geometry, spec)
    xml_bytes, _impedance = adapter._build_sim_xml(mesh, spec)
    observed_hash = hashlib.sha256(xml_bytes).hexdigest()
    expected_hash = _candidate_b_xml_hash(repo_root)
    if observed_hash != expected_hash:
        raise CrossCheckError(
            "candidate-B terminal retry XML differs from the pre-authorized 6x XML"
        )
    started_at = datetime.now(UTC)
    running = CandidateBTerminalState(
        status="running",
        started_at=started_at,
        expected_xml_sha256=expected_hash,
        observed_xml_sha256=observed_hash,
    )
    _write_json(state_path, running.model_dump(mode="json"))
    run_directory = repo_root / "runs" / CANDIDATE_B_OPENEMS_RUN_ID
    if run_directory.exists():
        openems_run = _load_candidate_b_run(repo_root)
    else:
        try:
            with _strict_solver_mode():
                curve = _curve(await adapter.solve(mesh, spec))
        except (SolverError, subprocess.TimeoutExpired) as error:
            if not _is_timeout_error(error):
                raise
            terminal = running.model_copy(
                update={
                    "status": "infeasible_at_current_compute",
                    "finished_at": datetime.now(UTC),
                    "failure": str(error),
                }
            )
            _write_json(state_path, terminal.model_dump(mode="json"))
            return terminal
        if curve.solver_mode != "subprocess":
            raise CrossCheckError(
                f"candidate B terminal retry is not real: {curve.solver_mode}"
            )
        config: dict[str, Any] = {
            "preregistration_commit": PREREGISTRATION_COMMIT,
            "replacement_preregistration_commit": (
                REBOOT_REPLACEMENT_PREREGISTRATION_COMMIT
            ),
            "replaces_interrupted_run_id": CANDIDATE_B_REBOOT_FAILURE_RUN_ID,
            "protocol_version": DAY65_REPAIR_PROTOCOL,
            "purpose": "candidate-B terminal retry and frozen re-verdict",
            "source_run_id": selected.source_run_id,
            "source_step_index": selected.source_step_index,
            "source_geometry_hash": selected.source_geometry_hash,
            "solver": "openems",
            "frequency_range_hz": FREEFORM_SWEEP_HZ,
            "frequency_points": FREEFORM_FREQUENCY_POINTS,
            "prior_timeout_seconds": 21600.0,
            "xml_sha256": observed_hash,
            **settings,
        }
        openems_run = Day6InstrumentRunSummary(
            run_id=CANDIDATE_B_OPENEMS_RUN_ID,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            seed=seed,
            config_hash=_canonical_hash(config),
            config=config,
            solver_mode_counts={"subprocess": 1},
            selected_design=selected,
            curve=curve,
        )
        _write_candidate_b_instrument_run(repo_root, openems_run)
    re_verdict = _build_candidate_b_reverdict(repo_root, selected, openems_run)
    terminal = running.model_copy(
        update={
            "status": "success",
            "finished_at": datetime.now(UTC),
            "re_verdict_run_id": re_verdict.run_id,
            "dual_band_verdict": re_verdict.dual_band_verdict,
            "discovery_verdict": re_verdict.discovery_verdict,
        }
    )
    _write_json(state_path, terminal.model_dump(mode="json"))
    return terminal


def load_candidate_b_terminal_state(repo_root: Path) -> CandidateBTerminalState:
    """Load the terminal result after the one authorized attempt."""

    state = CandidateBTerminalState.model_validate_json(
        _candidate_b_state_path(repo_root).read_text(encoding="utf-8")
    )
    if state.status == "running":
        raise CrossCheckError("candidate B terminal attempt has no terminal result")
    return state


def build_factor_audit_summary(repo_root: Path) -> Day65FactorAuditSummary:
    """Load source-addressed runs and apply only preregistered interpretations."""

    ordered_ids = (
        F3_L80_RUN_ID,
        F3_L320_RUN_ID,
        F4_NEC2_RUN_ID,
        F2_OPENEMS_RUN_ID,
        F4_OPENEMS_RUN_ID,
        F1_OPENEMS_RUN_ID,
    )
    runs = tuple(load_factor_run(repo_root, run_id) for run_id in ordered_ids)
    by_id = {item.run_id: item for item in runs}
    segmentation = classify_segmentation_stability(
        by_id[F3_L80_RUN_ID].resonance.frequency_hz,
        by_id[F3_L320_RUN_ID].resonance.frequency_hz,
    )
    if segmentation.classification != "segmentation_stable":
        raise CrossCheckError("analysis cannot proceed after unstable F3")
    f4_nec2 = by_id[F4_NEC2_RUN_ID]
    f2 = by_id[F2_OPENEMS_RUN_ID]
    f4_openems = by_id[F4_OPENEMS_RUN_ID]
    f1 = by_id[F1_OPENEMS_RUN_ID]
    residuals = (
        residual_bias(
            basis="radius-matched baseline",
            nec2_frequency_hz=BASELINE_NEC2_THICK_FREQUENCY_HZ,
            openems_frequency_hz=BASELINE_OPENEMS_FREQUENCY_HZ,
        ),
        residual_bias(
            basis="F1 grid-only",
            nec2_frequency_hz=BASELINE_NEC2_THICK_FREQUENCY_HZ,
            openems_frequency_hz=f1.resonance.frequency_hz,
        ),
        residual_bias(
            basis="F2 endcap-only",
            nec2_frequency_hz=BASELINE_NEC2_THICK_FREQUENCY_HZ,
            openems_frequency_hz=f2.resonance.frequency_hz,
        ),
        residual_bias(
            basis="F4 feed-gap differential",
            nec2_frequency_hz=f4_nec2.resonance.frequency_hz,
            openems_frequency_hz=f4_openems.resonance.frequency_hz,
        ),
    )
    correction = (
        "Do not change protocol thresholds from this audit; retain the measured "
        "single-factor shifts as an instrument systematic-error budget.",
        "If F1 is material, pre-register a further adjacent-grid convergence point "
        "before using the anchor as a frequency-calibration reference.",
        "If F2 is material, harmonize the two solvers on physical outer-envelope "
        "rather than centerline length in a future, separately preregistered anchor.",
        "If F4 is material, isolate the two feed representations with a dedicated "
        "port-deembedding study before changing any cross-solver gate.",
        "Candidate B is terminal under this authorization; its outcome must not "
        "trigger a third attempt without a new preregistration.",
    )
    return Day65FactorAuditSummary(
        generated_at=datetime.now(UTC),
        factor_runs=runs,
        segmentation=segmentation,
        residual_bias_estimates=residuals,
        candidate_b=load_candidate_b_terminal_state(repo_root),
        correction_proposal_v2=correction,
    )


def write_factor_audit_analysis(repo_root: Path) -> Day65FactorAuditSummary:
    """Write the requested JSON and Markdown analysis without altering old evidence."""

    summary = build_factor_audit_summary(repo_root)
    output = repo_root / ANALYSIS_RELATIVE_DIRECTORY
    _write_json(output / "summary.json", summary.model_dump(mode="json"))
    by_id = {item.run_id: item for item in summary.factor_runs}
    f3_80 = by_id[F3_L80_RUN_ID]
    f3_320 = by_id[F3_L320_RUN_ID]
    f4_nec2 = by_id[F4_NEC2_RUN_ID]
    f2 = by_id[F2_OPENEMS_RUN_ID]
    f4_openems = by_id[F4_OPENEMS_RUN_ID]
    f1 = by_id[F1_OPENEMS_RUN_ID]
    factor_rows = [
        (
            "F3 NEC2 lambda/80",
            f3_80,
            abs(f3_80.delta_frequency_hz),
            "segmentation diagnostic",
        ),
        (
            "F3 NEC2 lambda/320",
            f3_320,
            abs(f3_320.delta_frequency_hz),
            "segmentation diagnostic",
        ),
        (
            "F4 NEC2 0.3 mm gap",
            f4_nec2,
            abs(f4_nec2.delta_frequency_hz),
            "paired with F4 openEMS",
        ),
        (
            "F2 openEMS shortened ends",
            f2,
            abs(f2.delta_frequency_hz),
            str(f2.materiality),
        ),
        (
            "F4 openEMS 0.3 mm gap",
            f4_openems,
            float(f4_openems.decision_shift_hz or 0.0),
            str(f4_openems.materiality),
        ),
        (
            "F1 openEMS 8x/320k",
            f1,
            abs(f1.delta_frequency_hz),
            str(f1.materiality),
        ),
    ]
    lines = [
        "# Day 6.5 factorial anchor audit and candidate-B terminal retry",
        "",
        f"Pre-registration commit: `{PREREGISTRATION_COMMIT}`.",
        "",
        "No protocol, threshold, sweep, score, candidate, or prior run was changed.",
        "",
        "## Factor table",
        "",
        "| factor | f_res GHz | delta/decision MHz | result | source run |",
        "|---|---:|---:|---|---|",
    ]
    lines.extend(
        f"| {label} | {run.resonance.frequency_hz / 1e9:.3f} | "
        f"{shift / 1e6:.3f} | {result} | `{run.run_id}` |"
        for label, run, shift, result in factor_rows
    )
    lines.extend(
        [
            "",
            "## F3 segmentation stability",
            "",
            f"lambda/80={summary.segmentation.lambda80_frequency_hz / 1e9:.3f} GHz, "
            f"lambda/160={summary.segmentation.lambda160_frequency_hz / 1e9:.3f} GHz, "
            f"lambda/320={summary.segmentation.lambda320_frequency_hz / 1e9:.3f} GHz; "
            f"maximum shift={summary.segmentation.maximum_shift_hz / 1e6:.3f} MHz. "
            f"Classification: `{summary.segmentation.classification}`.",
            "",
            "## Per-factor residual frequency bias",
            "",
            "These are separate single-factor estimates and are not added together.",
            "",
            "| basis | NEC2 GHz | openEMS GHz | residual MHz |",
            "|---|---:|---:|---:|",
        ]
    )
    lines.extend(
        f"| {item.basis} | {item.nec2_frequency_hz / 1e9:.3f} | "
        f"{item.openems_frequency_hz / 1e9:.3f} | {item.residual_hz / 1e6:.3f} |"
        for item in summary.residual_bias_estimates
    )
    lines.extend(
        [
            "",
            "## Candidate B terminal outcome",
            "",
            f"Status: `{summary.candidate_b.status}`. Timeout authorization: "
            f"{summary.candidate_b.timeout_seconds:.0f} seconds. Re-verdict run: "
            f"`{summary.candidate_b.re_verdict_run_id}`. Dual-band verdict: "
            f"`{summary.candidate_b.dual_band_verdict}`. Discovery verdict: "
            f"`{summary.candidate_b.discovery_verdict}`.",
            "",
            "## Correction proposal v2 (not implemented)",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in summary.correction_proposal_v2)
    lines.append("")
    _write_text(output / "report.md", "\n".join(lines))
    return summary
