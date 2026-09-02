"""Bounded 5.8 GHz qualification of the resolved-rod openEMS renderer."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.cross_check import CrossCheckError, SolverCurve, _curve
from yaf_ai.exploration.cross_check_v2 import (
    ANCHOR_CORRELATION_THRESHOLD,
    ANCHOR_RESONANCE_THRESHOLD,
    AnchorDecision,
    evaluate_curves,
)
from yaf_ai.exploration.day6_cross_check import (
    BandResonanceValidity,
    band_validity,
)
from yaf_ai.exploration.freeform_wire import HIGH_BAND_HZ
from yaf_ai.exploration.patch_mesh_audit import (
    PatchMeshStatistics,
    parse_mesh_statistics,
)
from yaf_ai.exploration.semifinal_anchor import (
    C0,
    MEMORY_POLL_SECONDS,
    _curve_from_spectra,
    _process_tree_rss_bytes,
    _spec,
    _terminate_process_tree,
)
from yaf_ai.exploration.semifinal_anchor_r2 import (
    R2_FREQUENCY_POINTS,
    R2_GEOMETRY_SHA256,
    R2_SWEEP_HZ,
    semifinal_anchor_r2_geometry,
    validate_semifinal_anchor_r2_geometry,
)
from yaf_ai.exploration.semifinal_anchor_r3 import (
    FullSweepInteriorMinimum,
    RichardsonEstimate,
    SemifinalAnchorR3Summary,
    full_sweep_interior_minimum,
    full_sweep_shift,
    richardson_estimate,
)
from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter
from yaf_solvers.openems_adapter.port_parser import OpenEMSParseError, calc_port

ROD_PROTOCOL = "semifinal-wifi58-rod-renderer-anchor-r1"
ROD_RUN_ID = f"{ROD_PROTOCOL}-combined"
ROD_PREREGISTRATION_COMMIT = "4bca507"
ROD_REPRESENTATION = "rod"
ROD_REFINEMENTS = (1.0, 2.0, 4.0, 8.0)
ROD_CONVERGENCE_PAIR = (4.0, 8.0)
ROD_AGREEMENT_REFINEMENT = 8.0
ROD_CONVERGENCE_THRESHOLD = 0.03
ROD_TIMEOUT_SECONDS = 3600.0
ROD_RADIUS_M = 5e-5
LEGACY_R3_1X_XML_SHA256 = (
    "cfeb036bb550cf2a5847f4388b8ac2556a8752eff70180d555e6d1ce29aa94ad"
)
R3_LOG_SHA256_FROZEN = (
    "0e9da50876fa679870160ba9349a8391c18d7917355d7cef50177899bb967a9f"
)
R3_SUMMARY_SHA256_FROZEN = (
    "d5ac661dc0251d0e7dcecf7a88d967a2c510e568e3338a45c5e84399254f67a9"
)
R3_RUN_ID = "semifinal-wifi58-meander-renderer-anchor-r3-combined"
BUILD_ONLY_RELATIVE_PATH = (
    "artifacts/analysis/semifinal-wifi58-rod-renderer-anchor-r1/build-only.json"
)
TIMESTEP_PATTERN = re.compile(
    r"(?:FDTD timestep is:|Timestep \(s\)\s*:)\s*"
    r"(?P<value>[0-9.+\-eE]+)"
)
ITERATION_PATTERN = re.compile(r"Time for\s+(?P<value>\d+)\s+iterations")
TIMESTEP_CAP_PATTERN = re.compile(
    r"Max\. number of timesteps was reached", re.IGNORECASE
)

TerminationKind = Literal["end_criteria", "timestep_cap", "unknown"]
RodVerdict = Literal[
    "released",
    "not_released_not_converged",
    "not_released_resonance_invalid",
    "not_released_agreement",
]
InvalidSolver = Literal["nec2", "openems_8x"]
InvalidReason = Literal[
    "no_internal_minimum",
    "out_of_band_low",
    "out_of_band_high",
    "depth_above_minus_6_db",
]


class TerminationEvidence(BaseModel):
    """Auditable interpretation of one successful openEMS process stdout."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    executed_timesteps: int | None = Field(default=None, ge=0)
    openems_timestep_seconds: float | None = Field(default=None, gt=0.0)
    dt_proxy_seconds: float = Field(gt=0.0)
    actual_simulated_time_seconds: float | None = Field(default=None, ge=0.0)
    estimated_simulated_time_seconds: float | None = Field(default=None, ge=0.0)
    terminated_by: TerminationKind
    stdout_tail: tuple[str, ...]


class RodMeshDisclosure(BaseModel):
    """Build-only resource disclosure for one frozen rod refinement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refinement: float = Field(gt=0.0)
    mesh: PatchMeshStatistics
    dt_proxy_seconds: float = Field(gt=0.0)
    maximum_timesteps: int = Field(gt=0)
    cell_timesteps: int = Field(gt=0)
    per_axis_minimum_cell_size_m: tuple[float, float, float]
    per_axis_maximum_cell_size_m: tuple[float, float, float]


class RodBuildOnlyDisclosure(BaseModel):
    """Committed mesh-only disclosure produced before any rod solve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    protocol_version: str = ROD_PROTOCOL
    preregistration_commit: str = ROD_PREREGISTRATION_COMMIT
    solver_invoked: bool = False
    geometry_hash: str = R2_GEOMETRY_SHA256
    legacy_xml_sha256: str = LEGACY_R3_1X_XML_SHA256
    legacy_dt_proxy_seconds: float = Field(gt=0.0)
    target_physical_time_seconds: float = Field(gt=0.0)
    refinements: tuple[
        RodMeshDisclosure,
        RodMeshDisclosure,
        RodMeshDisclosure,
        RodMeshDisclosure,
    ]


class RodOpenEMSResult(BaseModel):
    """One real rod-renderer curve with resource and termination evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refinement: float = Field(gt=0.0)
    curve: SolverCurve
    mesh: PatchMeshStatistics
    maximum_timesteps: int = Field(gt=0)
    termination: TerminationEvidence
    peak_process_tree_memory_mb: float = Field(ge=0.0)
    elapsed_seconds: float = Field(ge=0.0)


class InvalidResonance(BaseModel):
    """First frozen resonance-validity failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    solver: InvalidSolver
    reason: InvalidReason


class RodAnchorDecision(BaseModel):
    """The frozen 4x/8x convergence and NEC2/8x agreement decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nec2_validity: BandResonanceValidity
    openems_4x_full_sweep_minimum: FullSweepInteriorMinimum
    openems_8x_full_sweep_minimum: FullSweepInteriorMinimum
    openems_8x_validity: BandResonanceValidity
    openems_4x_to_8x_resonance_shift: float | None = Field(default=None, ge=0.0)
    openems_convergence_threshold: float = ROD_CONVERGENCE_THRESHOLD
    openems_convergence_met: bool
    cross_solver_decision: AnchorDecision | None
    cross_solver_error: str | None
    invalid_resonance: InvalidResonance | None
    verdict: RodVerdict
    anchor_released: bool


class RetrospectiveRadiusDiagnostic(BaseModel):
    """Non-decision arithmetic for the disclosed post-r3 explanation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    length_m: float
    nec2_frequency_hz: float
    nec2_radius_m: float
    half_wave_frequency_hz: float
    fitted_k: float
    square_rod_equivalent_radius_m: float
    predicted_square_rod_frequency_hz: float
    diagnostic_only: bool = True
    retrospective: bool = True
    affects_verdict: bool = False


class NEC2Reproduction(BaseModel):
    """Raw NEC2 rerun difference from immutable r3 evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_run_id: str = R3_RUN_ID
    archived_frequency_hz: float
    rerun_frequency_hz: float
    frequency_difference_hz: float
    archived_s11_db: float
    rerun_s11_db: float
    s11_difference_db: float
    affects_verdict: bool = False


class RodAnchorSummary(BaseModel):
    """Archive-compatible successful rod qualification record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    result_status: Literal["completed"] = "completed"
    run_id: str = ROD_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 5
    evaluation_budget: int = 5
    solver_mode_counts: dict[str, int]
    geometry_hash: str
    geometry: dict[str, Any]
    build_only: RodBuildOnlyDisclosure
    nec2: SolverCurve
    openems_1x: RodOpenEMSResult
    openems_2x: RodOpenEMSResult
    openems_4x: RodOpenEMSResult
    openems_8x: RodOpenEMSResult
    decision: RodAnchorDecision
    richardson_estimate: RichardsonEstimate
    nec2_reproduction: NEC2Reproduction
    radius_diagnostic: RetrospectiveRadiusDiagnostic


class RodExecutionFailure(BaseModel):
    """Structured terminal execution failure outside the scientific verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_type: str
    refinement: float | None = Field(default=None, gt=0.0)
    message: str
    stdout_tail: tuple[str, ...] = ()
    scientific_verdict: None = None
    anchor_released: bool = False


class RodAnchorFailureSummary(BaseModel):
    """Archive-compatible zero-verdict terminal failure record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    result_status: Literal["execution_failed"] = "execution_failed"
    run_id: str = ROD_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = Field(ge=0, le=4)
    evaluation_budget: int = 5
    solver_mode_counts: dict[str, int]
    geometry_hash: str
    geometry: dict[str, Any]
    build_only: RodBuildOnlyDisclosure
    nec2: SolverCurve | None
    completed_openems: tuple[RodOpenEMSResult, ...]
    failure: RodExecutionFailure
    verdict: None = None
    anchor_released: bool = False


RodRunSummary = RodAnchorSummary | RodAnchorFailureSummary


class _RodLevelError(RuntimeError):
    def __init__(
        self,
        failure_type: str,
        message: str,
        *,
        refinement: float | None = None,
        stdout_tail: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.record = RodExecutionFailure(
            failure_type=failure_type,
            refinement=refinement,
            message=message,
            stdout_tail=stdout_tail,
        )


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _mesh(geometry: Geometry, run_id: str) -> Mesh:
    return Mesh(
        geometry_id=geometry.id,
        solver_name="openems",
        nodes=geometry.vertices,
        elements=[list(edge) for edge in geometry.faces],
        element_type="mixed",
        metadata={"job_id": run_id, **geometry.metadata},
    )


def _rod_spec(
    run_id: str,
    refinement: float,
    maximum_timesteps: int,
) -> SimulationSpec:
    return SimulationSpec(
        name=run_id,
        frequency_range=R2_SWEEP_HZ,
        frequency_points=R2_FREQUENCY_POINTS,
        solver_settings={
            "openems_mesh_refinement": refinement,
            "openems_timeout_seconds": ROD_TIMEOUT_SECONDS,
            "openems_wire_representation": ROD_REPRESENTATION,
            "openems_number_of_timesteps": maximum_timesteps,
        },
        far_field_request=None,
    )


def _grid_lines(xml_bytes: bytes) -> tuple[
    tuple[float, ...], tuple[float, ...], tuple[float, ...]
]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as error:
        raise CrossCheckError(f"invalid openEMS XML: {error}") from error
    grid = root.find("./ContinuousStructure/RectilinearGrid")
    if grid is None:
        raise CrossCheckError("simulation XML lacks RectilinearGrid")
    axes: list[tuple[float, ...]] = []
    for name in ("XLines", "YLines", "ZLines"):
        element = grid.find(name)
        if element is None or element.text is None:
            raise CrossCheckError(f"simulation XML lacks {name}")
        values = tuple(float(item) for item in element.text.split(","))
        if len(values) < 2 or any(
            right <= left for left, right in zip(values, values[1:], strict=False)
        ):
            raise CrossCheckError(f"simulation XML has invalid {name}")
        axes.append(values)
    return axes[0], axes[1], axes[2]


def cfl_dt_proxy(
    lines: tuple[Sequence[float], Sequence[float], Sequence[float]],
) -> float:
    """Return the preregistered deterministic Cartesian CFL proxy."""

    minima: list[float] = []
    for axis in lines:
        if len(axis) < 2:
            raise ValueError("each mesh axis must contain at least two lines")
        cells = [
            float(right) - float(left)
            for left, right in zip(axis, axis[1:], strict=False)
        ]
        if any(cell <= 0.0 or not math.isfinite(cell) for cell in cells):
            raise ValueError("mesh axes must be finite and strictly increasing")
        minima.append(min(cells))
    return 1.0 / (
        C0
        * math.sqrt(
            sum(1.0 / minimum**2 for minimum in minima)
        )
    )


def maximum_timesteps(target_time_seconds: float, dt_proxy_seconds: float) -> int:
    """Return the frozen ceiling preserving the legacy proxy time window."""

    if target_time_seconds <= 0.0 or dt_proxy_seconds <= 0.0:
        raise ValueError("time quantities must be positive")
    return math.ceil(target_time_seconds / dt_proxy_seconds)


def parse_termination(
    stdout_text: str,
    *,
    maximum_steps: int,
    dt_proxy_seconds: float,
) -> TerminationEvidence:
    """Parse the installed openEMS stdout conservatively."""

    timestep_matches = list(TIMESTEP_PATTERN.finditer(stdout_text))
    iteration_matches = list(ITERATION_PATTERN.finditer(stdout_text))
    timestep = (
        float(timestep_matches[-1].group("value")) if timestep_matches else None
    )
    iterations = (
        int(iteration_matches[-1].group("value")) if iteration_matches else None
    )
    if timestep is not None and (timestep <= 0.0 or not math.isfinite(timestep)):
        timestep = None
    if TIMESTEP_CAP_PATTERN.search(stdout_text) is not None:
        terminated_by: TerminationKind = "timestep_cap"
    elif iterations is not None and iterations < maximum_steps:
        terminated_by = "end_criteria"
    elif iterations is not None and iterations >= maximum_steps:
        terminated_by = "timestep_cap"
    else:
        terminated_by = "unknown"
    actual = None if timestep is None or iterations is None else timestep * iterations
    estimated = None if iterations is None else dt_proxy_seconds * iterations
    return TerminationEvidence(
        executed_timesteps=iterations,
        openems_timestep_seconds=timestep,
        dt_proxy_seconds=dt_proxy_seconds,
        actual_simulated_time_seconds=actual,
        estimated_simulated_time_seconds=estimated,
        terminated_by=terminated_by,
        stdout_tail=tuple(stdout_text.splitlines()[-20:]),
    )


def _legacy_reference(
    geometry: Geometry,
) -> tuple[str, float, float]:
    adapter = OpenEMSAdapter()
    mesh = _mesh(
        geometry,
        f"{R3_RUN_ID}-openems-1x",
    )
    spec = _spec(f"{R3_RUN_ID}-openems-1x", refinement=1.0)
    xml_bytes, _impedance = adapter._build_sim_xml(mesh, spec)
    digest = hashlib.sha256(xml_bytes).hexdigest()
    if digest != LEGACY_R3_1X_XML_SHA256:
        raise CrossCheckError("legacy r3 1x XML SHA-256 changed")
    dt_proxy = cfl_dt_proxy(_grid_lines(xml_bytes))
    return digest, dt_proxy, 40000.0 * dt_proxy


def build_rod_disclosures(geometry: Geometry) -> RodBuildOnlyDisclosure:
    """Build all frozen meshes without running either numerical solver."""

    geometry_hash = validate_semifinal_anchor_r2_geometry(geometry)
    if geometry_hash != R2_GEOMETRY_SHA256:
        raise CrossCheckError("rod anchor geometry differs from frozen r2")
    radius = geometry.metadata.get("wire_radius_m")
    if radius != ROD_RADIUS_M:
        raise CrossCheckError("rod anchor wire radius differs from frozen r2")
    legacy_hash, legacy_dt, target_time = _legacy_reference(geometry)
    adapter = OpenEMSAdapter()
    mesh = _mesh(geometry, ROD_RUN_ID)
    rows: list[RodMeshDisclosure] = []
    for refinement in ROD_REFINEMENTS:
        preliminary_spec = _rod_spec(
            f"{ROD_RUN_ID}-openems-{refinement:g}x",
            refinement,
            40000,
        )
        preliminary_xml, _ = adapter._build_sim_xml(mesh, preliminary_spec)
        preliminary_lines = _grid_lines(preliminary_xml)
        dt_proxy = cfl_dt_proxy(preliminary_lines)
        steps = maximum_timesteps(target_time, dt_proxy)
        final_spec = _rod_spec(
            f"{ROD_RUN_ID}-openems-{refinement:g}x",
            refinement,
            steps,
        )
        xml_bytes, _ = adapter._build_sim_xml(mesh, final_spec)
        final_lines = _grid_lines(xml_bytes)
        if final_lines != preliminary_lines:
            raise CrossCheckError("rod time-step ceiling changed the final grid")
        statistics = parse_mesh_statistics(xml_bytes, refinement)
        rows.append(
            RodMeshDisclosure(
                refinement=refinement,
                mesh=statistics,
                dt_proxy_seconds=dt_proxy,
                maximum_timesteps=steps,
                cell_timesteps=statistics.total_cells * steps,
                per_axis_minimum_cell_size_m=(
                    statistics.x.minimum_cell_size_m,
                    statistics.y.minimum_cell_size_m,
                    statistics.z.minimum_cell_size_m,
                ),
                per_axis_maximum_cell_size_m=(
                    statistics.x.maximum_cell_size_m,
                    statistics.y.maximum_cell_size_m,
                    statistics.z.maximum_cell_size_m,
                ),
            )
        )
    one, two, four, eight = rows
    return RodBuildOnlyDisclosure(
        legacy_xml_sha256=legacy_hash,
        legacy_dt_proxy_seconds=legacy_dt,
        target_physical_time_seconds=target_time,
        refinements=(one, two, four, eight),
    )


def write_build_only_disclosure(repo_root: Path) -> RodBuildOnlyDisclosure:
    """Persist the preregistered no-solve resource disclosure with LF bytes."""

    disclosure = build_rod_disclosures(semifinal_anchor_r2_geometry())
    path = repo_root / BUILD_ONLY_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(
                disclosure.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    return disclosure


def retrospective_radius_diagnostic() -> RetrospectiveRadiusDiagnostic:
    """Compute the disclosed post-r3 arithmetic without fitting any run."""

    length = float(semifinal_anchor_r2_geometry().metadata["length_m"])
    half_wave = C0 / (2.0 * length)
    nec2_frequency = 5.8e9
    fitted_k = (1.0 - nec2_frequency / half_wave) * math.log(
        length / ROD_RADIUS_M
    )
    equivalent = 0.59 * 2.0 * ROD_RADIUS_M
    prediction = half_wave * (
        1.0 - fitted_k / math.log(length / equivalent)
    )
    return RetrospectiveRadiusDiagnostic(
        length_m=length,
        nec2_frequency_hz=nec2_frequency,
        nec2_radius_m=ROD_RADIUS_M,
        half_wave_frequency_hz=half_wave,
        fitted_k=fitted_k,
        square_rod_equivalent_radius_m=equivalent,
        predicted_square_rod_frequency_hz=prediction,
    )


def _invalid_reason(curve: SolverCurve) -> InvalidReason | None:
    full = full_sweep_interior_minimum(curve)
    if not full.valid:
        return "no_internal_minimum"
    if full.minimum_frequency_hz < HIGH_BAND_HZ[0]:
        return "out_of_band_low"
    if full.minimum_frequency_hz > HIGH_BAND_HZ[1]:
        return "out_of_band_high"
    validity = band_validity(curve, HIGH_BAND_HZ)
    if not validity.local_minimum or not validity.wide_sweep_interior:
        return "no_internal_minimum"
    if not validity.depth_threshold_met:
        return "depth_above_minus_6_db"
    return None


def evaluate_rod_anchor(
    nec2: SolverCurve,
    openems_4x: RodOpenEMSResult,
    openems_8x: RodOpenEMSResult,
) -> RodAnchorDecision:
    """Apply only the frozen decision levels, gates, and reason priority."""

    if (
        nec2.frequency_hz != openems_4x.curve.frequency_hz
        or nec2.frequency_hz != openems_8x.curve.frequency_hz
        or len(nec2.frequency_hz) != R2_FREQUENCY_POINTS
    ):
        raise CrossCheckError("rod anchor frequency arrays differ")
    nec2_validity = band_validity(nec2, HIGH_BAND_HZ)
    four_minimum = full_sweep_interior_minimum(openems_4x.curve)
    eight_minimum = full_sweep_interior_minimum(openems_8x.curve)
    eight_validity = band_validity(openems_8x.curve, HIGH_BAND_HZ)
    shift = full_sweep_shift(openems_4x.curve, openems_8x.curve)
    convergence_met = (
        shift is not None
        and shift <= ROD_CONVERGENCE_THRESHOLD
        and openems_4x.termination.terminated_by != "timestep_cap"
        and openems_8x.termination.terminated_by != "timestep_cap"
    )
    cross_solver: AnchorDecision | None = None
    cross_error: str | None = None
    try:
        evaluated = evaluate_curves(openems_8x.curve, nec2, anchor=True)
        if not isinstance(evaluated, AnchorDecision):
            raise AssertionError("rod anchor evaluator returned non-anchor decision")
        cross_solver = evaluated
    except CrossCheckError as error:
        cross_error = str(error)

    invalid: InvalidResonance | None = None
    nec2_reason = _invalid_reason(nec2)
    openems_reason = _invalid_reason(openems_8x.curve)
    if not convergence_met:
        verdict: RodVerdict = "not_released_not_converged"
    elif nec2_reason is not None:
        invalid = InvalidResonance(solver="nec2", reason=nec2_reason)
        verdict = "not_released_resonance_invalid"
    elif openems_reason is not None:
        invalid = InvalidResonance(solver="openems_8x", reason=openems_reason)
        verdict = "not_released_resonance_invalid"
    elif cross_solver is None or cross_solver.verdict != "CONFIRMED":
        verdict = "not_released_agreement"
    else:
        verdict = "released"
    return RodAnchorDecision(
        nec2_validity=nec2_validity,
        openems_4x_full_sweep_minimum=four_minimum,
        openems_8x_full_sweep_minimum=eight_minimum,
        openems_8x_validity=eight_validity,
        openems_4x_to_8x_resonance_shift=shift,
        openems_convergence_met=convergence_met,
        cross_solver_decision=cross_solver,
        cross_solver_error=cross_error,
        invalid_resonance=invalid,
        verdict=verdict,
        anchor_released=verdict == "released",
    )


def _run_rod_level(
    geometry: Geometry,
    disclosure: RodMeshDisclosure,
    run_id: str,
) -> RodOpenEMSResult:
    adapter = OpenEMSAdapter()
    executable = adapter._resolve_executable()
    if executable is None:
        raise _RodLevelError(
            "solver_unavailable",
            "real openEMS executable is unavailable",
            refinement=disclosure.refinement,
        )
    spec = _rod_spec(
        run_id,
        disclosure.refinement,
        disclosure.maximum_timesteps,
    )
    mesh = _mesh(geometry, run_id)
    xml_bytes, impedance = adapter._build_sim_xml(mesh, spec)
    statistics = parse_mesh_statistics(xml_bytes, disclosure.refinement)
    if statistics.xml_sha256 != disclosure.mesh.xml_sha256:
        raise _RodLevelError(
            "xml_identity_mismatch",
            "rod XML differs from the committed build-only disclosure",
            refinement=disclosure.refinement,
        )
    with tempfile.TemporaryDirectory(prefix="semifinal_rod_anchor_") as temp:
        directory = Path(temp)
        (directory / "sim.xml").write_bytes(xml_bytes)
        stdout_path = directory / "openems.stdout.log"
        stderr_path = directory / "openems.stderr.log"
        started = time.monotonic()
        peak_bytes = 0
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                process = subprocess.Popen(
                    [executable, "sim.xml"],
                    cwd=directory,
                    stdout=stdout,
                    stderr=stderr,
                )
            except OSError as error:
                raise _RodLevelError(
                    "solver_launch_failed",
                    f"openEMS could not be launched: {error}",
                    refinement=disclosure.refinement,
                ) from error
            while process.poll() is None:
                peak_bytes = max(
                    peak_bytes,
                    _process_tree_rss_bytes(process.pid),
                )
                if time.monotonic() - started > ROD_TIMEOUT_SECONDS:
                    _terminate_process_tree(process)
                    process.wait()
                    stdout.flush()
                    stderr.flush()
                    stdout_text = stdout_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    raise _RodLevelError(
                        "timeout",
                        (
                            f"openEMS rod anchor {disclosure.refinement:g}x "
                            f"exceeded {ROD_TIMEOUT_SECONDS:.0f} seconds"
                        ),
                        refinement=disclosure.refinement,
                        stdout_tail=tuple(stdout_text.splitlines()[-20:]),
                    )
                time.sleep(MEMORY_POLL_SECONDS)
        elapsed = time.monotonic() - started
        peak_bytes = max(peak_bytes, _process_tree_rss_bytes(process.pid))
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
        if process.returncode != 0:
            raise _RodLevelError(
                "nonzero_exit",
                (
                    f"openEMS rod anchor {disclosure.refinement:g}x exited "
                    f"{process.returncode}: {stderr_text[-500:]}"
                ),
                refinement=disclosure.refinement,
                stdout_tail=tuple(stdout_text.splitlines()[-20:]),
            )
        termination = parse_termination(
            stdout_text,
            maximum_steps=disclosure.maximum_timesteps,
            dt_proxy_seconds=disclosure.dt_proxy_seconds,
        )
        if termination.terminated_by == "unknown":
            raise _RodLevelError(
                "termination_unknown",
                "openEMS termination reason could not be parsed",
                refinement=disclosure.refinement,
                stdout_tail=termination.stdout_tail,
            )
        frequency_hz = np.linspace(
            R2_SWEEP_HZ[0],
            R2_SWEEP_HZ[1],
            R2_FREQUENCY_POINTS,
        ).tolist()
        try:
            spectra = calc_port(directory, 1, frequency_hz, z_ref=impedance)
        except (OpenEMSParseError, OSError, ValueError) as error:
            raise _RodLevelError(
                "port_data_missing",
                f"openEMS port data could not be parsed: {error}",
                refinement=disclosure.refinement,
                stdout_tail=termination.stdout_tail,
            ) from error
        curve = _curve_from_spectra(frequency_hz, spectra.s11, elapsed)
    return RodOpenEMSResult(
        refinement=disclosure.refinement,
        curve=curve,
        mesh=statistics,
        maximum_timesteps=disclosure.maximum_timesteps,
        termination=termination,
        peak_process_tree_memory_mb=peak_bytes / (1024.0 * 1024.0),
        elapsed_seconds=elapsed,
    )


def _load_r3_summary(repo_root: Path) -> SemifinalAnchorR3Summary:
    directory = repo_root / "artifacts" / "runs" / R3_RUN_ID
    log_bytes = (directory / "log.jsonl").read_bytes()
    summary_bytes = (directory / "summary.json").read_bytes()
    if hashlib.sha256(log_bytes).hexdigest() != R3_LOG_SHA256_FROZEN:
        raise CrossCheckError("archived r3 log SHA-256 changed")
    if hashlib.sha256(summary_bytes).hexdigest() != R3_SUMMARY_SHA256_FROZEN:
        raise CrossCheckError("archived r3 summary SHA-256 changed")
    return SemifinalAnchorR3Summary.model_validate_json(summary_bytes)


def _config(
    geometry: Geometry,
    build_only: RodBuildOnlyDisclosure,
) -> dict[str, Any]:
    return {
        "protocol_version": ROD_PROTOCOL,
        "preregistration_commit": ROD_PREREGISTRATION_COMMIT,
        "geometry_hash": R2_GEOMETRY_SHA256,
        "geometry": geometry.metadata,
        "frequency_range_hz": R2_SWEEP_HZ,
        "frequency_points": R2_FREQUENCY_POINTS,
        "wire_representation": ROD_REPRESENTATION,
        "wire_radius_m": ROD_RADIUS_M,
        "openems_refinements": ROD_REFINEMENTS,
        "openems_convergence_pair": ROD_CONVERGENCE_PAIR,
        "cross_solver_openems_refinement": ROD_AGREEMENT_REFINEMENT,
        "openems_convergence_threshold": ROD_CONVERGENCE_THRESHOLD,
        "anchor_resonance_threshold": ANCHOR_RESONANCE_THRESHOLD,
        "anchor_pearson_threshold": ANCHOR_CORRELATION_THRESHOLD,
        "openems_timeout_seconds": ROD_TIMEOUT_SECONDS,
        "target_physical_time_seconds": build_only.target_physical_time_seconds,
        "build_only_file": BUILD_ONLY_RELATIVE_PATH,
    }


def _write_payload(
    run_directory: Path,
    summary: RodRunSummary,
) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    event = {
        "schema_version": 1,
        "event_type": "semifinal_rod_anchor_result",
        "run_id": summary.run_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "result_status": summary.result_status,
        "summary": summary.model_dump(mode="json"),
    }
    (run_directory / "log.jsonl").write_bytes(
        (
            json.dumps(
                event, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            + "\n"
        ).encode("utf-8")
    )
    temporary = run_directory / "summary.json.tmp"
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
    os.replace(temporary, run_directory / "summary.json")


def _load_existing(path: Path) -> RodRunSummary:
    payload = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    if payload.get("result_status") == "execution_failed":
        return RodAnchorFailureSummary.model_validate(payload)
    return RodAnchorSummary.model_validate(payload)


async def run_rod_anchor(
    repo_root: Path,
    run_id: str = ROD_RUN_ID,
) -> RodRunSummary:
    """Run the frozen rod qualification and persist success or terminal failure."""

    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        return _load_existing(run_directory)
    started_at = datetime.now(UTC)
    geometry = semifinal_anchor_r2_geometry()
    geometry_hash = validate_semifinal_anchor_r2_geometry(geometry)
    if geometry_hash != R2_GEOMETRY_SHA256:
        raise CrossCheckError("rod anchor did not reuse the exact r2 geometry")
    build_only = build_rod_disclosures(geometry)
    committed_disclosure_path = repo_root / BUILD_ONLY_RELATIVE_PATH
    if not committed_disclosure_path.exists():
        raise CrossCheckError("committed build-only disclosure is missing")
    committed = RodBuildOnlyDisclosure.model_validate_json(
        committed_disclosure_path.read_text(encoding="utf-8")
    )
    if committed != build_only:
        raise CrossCheckError("committed build-only disclosure changed")
    config = _config(geometry, build_only)
    config_hash = _canonical_hash(config)
    completed: list[RodOpenEMSResult] = []
    nec2: SolverCurve | None = None
    try:
        adapter = NEC2Adapter()
        nec2_spec = _spec(f"{run_id}-nec2")
        try:
            nec2_mesh = await adapter.mesh(geometry, nec2_spec)
            nec2 = _curve(await adapter.solve(nec2_mesh, nec2_spec))
        except (CrossCheckError, OSError, subprocess.SubprocessError, ValueError) as error:
            raise _RodLevelError(
                "nec2_execution_failed",
                f"NEC2 rod anchor execution failed: {error}",
            ) from error
        if nec2.solver_mode != "subprocess":
            raise _RodLevelError(
                "fallback",
                f"rod anchor NEC2 is not real: {nec2.solver_mode}",
            )
        for disclosure in build_only.refinements:
            completed.append(
                _run_rod_level(
                    geometry,
                    disclosure,
                    f"{run_id}-openems-{disclosure.refinement:g}x",
                )
            )
    except _RodLevelError as error:
        failure = RodAnchorFailureSummary(
            run_id=run_id,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            config_hash=config_hash,
            config=config,
            steps_completed=(1 if nec2 is not None else 0) + len(completed),
            solver_mode_counts={
                "subprocess": (1 if nec2 is not None else 0) + len(completed)
            },
            geometry_hash=geometry_hash,
            geometry=geometry.model_dump(mode="json", exclude={"id"}),
            build_only=build_only,
            nec2=nec2,
            completed_openems=tuple(completed),
            failure=error.record,
        )
        _write_payload(run_directory, failure)
        return failure

    if nec2 is None or len(completed) != 4:
        raise AssertionError("rod qualification completed an impossible solve count")
    one, two, four, eight = completed
    decision = evaluate_rod_anchor(nec2, four, eight)
    r3 = _load_r3_summary(repo_root)
    reproduction = NEC2Reproduction(
        archived_frequency_hz=r3.nec2.resonance_frequency_hz,
        rerun_frequency_hz=nec2.resonance_frequency_hz,
        frequency_difference_hz=(
            nec2.resonance_frequency_hz - r3.nec2.resonance_frequency_hz
        ),
        archived_s11_db=r3.nec2.resonance_s11_db,
        rerun_s11_db=nec2.resonance_s11_db,
        s11_difference_db=nec2.resonance_s11_db - r3.nec2.resonance_s11_db,
    )
    summary = RodAnchorSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=config_hash,
        config=config,
        solver_mode_counts={"subprocess": 5},
        geometry_hash=geometry_hash,
        geometry=geometry.model_dump(mode="json", exclude={"id"}),
        build_only=build_only,
        nec2=nec2,
        openems_1x=one,
        openems_2x=two,
        openems_4x=four,
        openems_8x=eight,
        decision=decision,
        richardson_estimate=richardson_estimate(
            two.curve, four.curve, eight.curve
        ),
        nec2_reproduction=reproduction,
        radius_diagnostic=retrospective_radius_diagnostic(),
    )
    _write_payload(run_directory, summary)
    return summary
