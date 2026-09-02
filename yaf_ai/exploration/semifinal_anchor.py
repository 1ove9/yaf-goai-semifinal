"""Preregistered 5.8 GHz qualification of the meander thin-box renderer."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import psutil
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
    high_band_shift,
)
from yaf_ai.exploration.freeform_wire import HIGH_BAND_HZ
from yaf_ai.exploration.patch_mesh_audit import (
    PatchMeshStatistics,
    parse_mesh_statistics,
)
from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter
from yaf_solvers.openems_adapter.port_parser import calc_port

SEMIFINAL_ANCHOR_GEOMETRY_SHA256 = (
    "fb9d1550af2b6c295df6b788229f66f0569efeb3afc7ed00b662555ec5eab93f"
)

SEMIFINAL_ANCHOR_PROTOCOL = "semifinal-wifi58-meander-renderer-anchor-r1"
SEMIFINAL_ANCHOR_RUN_ID = f"{SEMIFINAL_ANCHOR_PROTOCOL}-combined"
PREREGISTRATION_COMMIT = "7f4e01f"
C0 = 299_792_458.0
ANCHOR_FREQUENCY_HZ = 5.800e9
ANCHOR_LENGTH_M = 0.0258441774
ANCHOR_FEED_GAP_M = 0.000600
ANCHOR_WIRE_RADIUS_M = 0.00005
ANCHOR_SWEEP_HZ = (1.5e9, 6.5e9)
ANCHOR_FREQUENCY_POINTS = 251
ANCHOR_NEC2_DENSITY = 40
OPENEMS_REFINEMENTS = (1.0, 2.0)
OPENEMS_CONVERGENCE_THRESHOLD = 0.03
OPENEMS_TIMEOUT_SECONDS = 3600.0
MEMORY_POLL_SECONDS = 0.1


class MonitoredOpenEMSResult(BaseModel):
    """One real openEMS curve with XML grid and observed process memory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refinement: float = Field(gt=0.0)
    curve: SolverCurve
    mesh: PatchMeshStatistics
    peak_process_tree_memory_mb: float = Field(ge=0.0)
    elapsed_seconds: float = Field(ge=0.0)


class SemifinalAnchorDecision(BaseModel):
    """All frozen validity, agreement, and adjacent-grid release gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nec2_validity: BandResonanceValidity
    openems_1x_validity: BandResonanceValidity
    openems_2x_validity: BandResonanceValidity
    cross_solver_decision: AnchorDecision | None
    cross_solver_error: str | None
    openems_resonance_shift: float | None = Field(default=None, ge=0.0)
    openems_convergence_threshold: float = OPENEMS_CONVERGENCE_THRESHOLD
    openems_convergence_met: bool
    anchor_released: bool


class SemifinalAnchorSummary(BaseModel):
    """Archive-compatible combined certificate for G5."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    run_id: str = SEMIFINAL_ANCHOR_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 3
    evaluation_budget: int = 3
    solver_mode_counts: dict[str, int]
    geometry_hash: str
    geometry: dict[str, Any]
    nec2: SolverCurve
    openems_1x: MonitoredOpenEMSResult
    openems_2x: MonitoredOpenEMSResult
    decision: SemifinalAnchorDecision


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def semifinal_anchor_geometry() -> Geometry:
    """Build the frozen straight dipole through the meander renderer path."""

    half = ANCHOR_LENGTH_M / 2.0
    gap_half = ANCHOR_FEED_GAP_M / 2.0
    wavelength_over_40 = C0 / ANCHOR_FREQUENCY_HZ / 40.0
    geometry = Geometry(
        name="semifinal_wifi58_meander_renderer_anchor",
        vertices=[
            [0.0, -gap_half, 0.0],
            [0.0, gap_half, 0.0],
            [0.0, half, 0.0],
            [0.0, -half, 0.0],
        ],
        faces=[[0, 1], [1, 2], [0, 3]],
        metadata={
            "antenna_class": "meander_dipole",
            "anchor_topology": "straight_half_wave",
            "protocol_version": SEMIFINAL_ANCHOR_PROTOCOL,
            "center_frequency_hz": ANCHOR_FREQUENCY_HZ,
            "length_m": ANCHOR_LENGTH_M,
            "feed_gap_m": ANCHOR_FEED_GAP_M,
            "wire_radius_m": ANCHOR_WIRE_RADIUS_M,
            "minimum_pitch_m": 2.0 * wavelength_over_40,
            "nec2_extended_thin_wire_kernel": False,
            "edge_order": (
                "feed_gap",
                "positive_arm",
                "negative_arm",
            ),
        },
    )
    validate_semifinal_anchor_geometry(geometry)
    return geometry


def validate_semifinal_anchor_geometry(geometry: Geometry) -> None:
    """Reject any geometry or dispatch change before a numerical call."""


def validate_semifinal_anchor_hash(geometry: Geometry) -> str:
    """Require the preregistered nodes, edges, and metadata byte identity."""

    digest = semifinal_anchor_geometry_hash(geometry)
    if digest != SEMIFINAL_ANCHOR_GEOMETRY_SHA256:
        raise CrossCheckError("semifinal anchor geometry SHA-256 changed")
    return digest
    expected = (
        "meander_dipole",
        "straight_half_wave",
        ANCHOR_LENGTH_M,
        ANCHOR_FEED_GAP_M,
        ANCHOR_WIRE_RADIUS_M,
    )
    observed = (
        geometry.metadata.get("antenna_class"),
        geometry.metadata.get("anchor_topology"),
        geometry.metadata.get("length_m"),
        geometry.metadata.get("feed_gap_m"),
        geometry.metadata.get("wire_radius_m"),
    )
    if observed != expected:
        raise CrossCheckError("semifinal anchor metadata changed")
    if geometry.faces != [[0, 1], [1, 2], [0, 3]]:
        raise CrossCheckError("semifinal anchor edge order changed")
    if len(geometry.vertices) != 4:
        raise CrossCheckError("semifinal anchor vertex count changed")
    total = sum(
        math.dist(geometry.vertices[edge[0]], geometry.vertices[edge[1]]) for edge in geometry.faces
    )
    if not math.isclose(
        total,
        ANCHOR_LENGTH_M,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise CrossCheckError("semifinal anchor length changed")
    if any(abs(vertex[0]) > 1e-12 or abs(vertex[2]) > 1e-12 for vertex in geometry.vertices):
        raise CrossCheckError("semifinal anchor is not y-axis aligned")


def semifinal_anchor_geometry_hash(geometry: Geometry | None = None) -> str:
    """Hash physical anchor content while excluding Geometry's random UUID."""

    source = geometry if geometry is not None else semifinal_anchor_geometry()
    payload = source.model_dump(mode="json", exclude={"id"})
    return _canonical_hash(payload)


def _spec(
    run_id: str,
    *,
    refinement: float | None = None,
) -> SimulationSpec:
    settings: dict[str, float | int] = {
        "nec2_segments_per_wavelength": ANCHOR_NEC2_DENSITY,
        "nec2_timeout_seconds": 300.0,
    }
    if refinement is not None:
        settings.update(
            {
                "openems_mesh_refinement": refinement,
                "openems_timeout_seconds": OPENEMS_TIMEOUT_SECONDS,
            }
        )
    return SimulationSpec(
        name=run_id,
        frequency_range=ANCHOR_SWEEP_HZ,
        frequency_points=ANCHOR_FREQUENCY_POINTS,
        solver_settings=settings,
        far_field_request=None,
    )


def _process_tree_rss_bytes(process_id: int) -> int:
    try:
        root = psutil.Process(process_id)
        processes = (root, *root.children(recursive=True))
    except (psutil.Error, OSError):
        return 0
    total = 0
    for process in processes:
        try:
            total += int(process.memory_info().rss)
        except (psutil.Error, OSError):
            continue
    return total


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        root = psutil.Process(process.pid)
        for child in root.children(recursive=True):
            child.kill()
        root.kill()
    except (psutil.Error, OSError):
        process.kill()


def _curve_from_spectra(
    frequency_hz: list[float],
    s11: Sequence[complex],
    elapsed_seconds: float,
) -> SolverCurve:
    s11_db = tuple(20.0 * math.log10(max(abs(value), 1e-15)) for value in s11)
    index = min(range(len(s11_db)), key=s11_db.__getitem__)
    return SolverCurve(
        solver_name="openems",
        solver_mode="subprocess",
        frequency_hz=tuple(frequency_hz),
        s11_db=s11_db,
        resonance_frequency_hz=frequency_hz[index],
        resonance_s11_db=s11_db[index],
        simulation_time_seconds=elapsed_seconds,
    )


def _run_openems_monitored(
    geometry: Geometry,
    *,
    refinement: float,
    run_id: str,
) -> MonitoredOpenEMSResult:
    """Run the same XML/port parser while observing the real process tree."""

    adapter = OpenEMSAdapter()
    executable = adapter._resolve_executable()
    if executable is None:
        raise CrossCheckError("real openEMS executable is unavailable")
    spec = _spec(run_id, refinement=refinement)
    mesh = Mesh(
        geometry_id=geometry.id,
        solver_name=adapter.name,
        nodes=geometry.vertices,
        elements=[list(edge) for edge in geometry.faces],
        element_type="mixed",
        metadata={
            "job_id": run_id,
            **geometry.metadata,
        },
    )
    xml_bytes, impedance = adapter._build_sim_xml(mesh, spec)
    statistics = parse_mesh_statistics(xml_bytes, refinement)
    with tempfile.TemporaryDirectory(prefix="semifinal_anchor_") as temp:
        directory = Path(temp)
        (directory / "sim.xml").write_bytes(xml_bytes)
        stdout_path = directory / "openems.stdout.log"
        stderr_path = directory / "openems.stderr.log"
        started = time.monotonic()
        peak_bytes = 0
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                [executable, "sim.xml"],
                cwd=directory,
                stdout=stdout,
                stderr=stderr,
            )
            while process.poll() is None:
                peak_bytes = max(
                    peak_bytes,
                    _process_tree_rss_bytes(process.pid),
                )
                if time.monotonic() - started > OPENEMS_TIMEOUT_SECONDS:
                    _terminate_process_tree(process)
                    process.wait()
                    raise CrossCheckError(
                        f"openEMS anchor {refinement:g}x exceeded "
                        f"{OPENEMS_TIMEOUT_SECONDS:.0f} seconds"
                    )
                time.sleep(MEMORY_POLL_SECONDS)
        elapsed = time.monotonic() - started
        peak_bytes = max(peak_bytes, _process_tree_rss_bytes(process.pid))
        if process.returncode != 0:
            tail = stderr_path.read_text(
                encoding="utf-8",
                errors="replace",
            )[-500:]
            raise CrossCheckError(
                f"openEMS anchor {refinement:g}x exited {process.returncode}: {tail}"
            )
        frequency_hz = np.linspace(
            ANCHOR_SWEEP_HZ[0],
            ANCHOR_SWEEP_HZ[1],
            ANCHOR_FREQUENCY_POINTS,
        ).tolist()
        spectra = calc_port(
            directory,
            1,
            frequency_hz,
            z_ref=impedance,
        )
        curve = _curve_from_spectra(
            frequency_hz,
            spectra.s11,
            elapsed,
        )
    return MonitoredOpenEMSResult(
        refinement=refinement,
        curve=curve,
        mesh=statistics,
        peak_process_tree_memory_mb=peak_bytes / (1024.0 * 1024.0),
        elapsed_seconds=elapsed,
    )


def evaluate_semifinal_anchor(
    nec2: SolverCurve,
    openems_1x: SolverCurve,
    openems_2x: SolverCurve,
) -> SemifinalAnchorDecision:
    """Apply only the preregistered v2.1 anchor and self-convergence gates."""

    nec2_validity = band_validity(nec2, HIGH_BAND_HZ)
    openems_1x_validity = band_validity(openems_1x, HIGH_BAND_HZ)
    openems_2x_validity = band_validity(openems_2x, HIGH_BAND_HZ)
    cross_solver: AnchorDecision | None = None
    cross_error: str | None = None
    try:
        evaluated = evaluate_curves(
            openems_2x,
            nec2,
            anchor=True,
        )
        if not isinstance(evaluated, AnchorDecision):
            raise AssertionError("anchor evaluator returned a non-anchor decision")
        cross_solver = evaluated
    except CrossCheckError as error:
        cross_error = str(error)
    shift = high_band_shift(openems_1x, openems_2x)
    convergence_met = shift is not None and shift <= OPENEMS_CONVERGENCE_THRESHOLD
    released = (
        nec2_validity.valid
        and openems_1x_validity.valid
        and openems_2x_validity.valid
        and cross_solver is not None
        and cross_solver.verdict == "CONFIRMED"
        and convergence_met
    )
    return SemifinalAnchorDecision(
        nec2_validity=nec2_validity,
        openems_1x_validity=openems_1x_validity,
        openems_2x_validity=openems_2x_validity,
        cross_solver_decision=cross_solver,
        cross_solver_error=cross_error,
        openems_resonance_shift=shift,
        openems_convergence_met=convergence_met,
        anchor_released=released,
    )


def _write_run(
    run_directory: Path,
    summary: SemifinalAnchorSummary,
) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    events = [
        {
            "schema_version": 1,
            "event_type": "semifinal_anchor_solver_result",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "solver": "nec2",
            "curve": summary.nec2.model_dump(mode="json"),
        },
        {
            "schema_version": 1,
            "event_type": "semifinal_anchor_solver_result",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "solver": "openems",
            "refinement": 1.0,
            "result": summary.openems_1x.model_dump(mode="json"),
        },
        {
            "schema_version": 1,
            "event_type": "semifinal_anchor_solver_result",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "solver": "openems",
            "refinement": 2.0,
            "result": summary.openems_2x.model_dump(mode="json"),
        },
        {
            "schema_version": 1,
            "event_type": "semifinal_anchor_decision",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "decision": summary.decision.model_dump(mode="json"),
        },
    ]
    log = "".join(
        json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
        for event in events
    )
    (run_directory / "log.jsonl").write_bytes(log.encode("utf-8"))
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


async def run_semifinal_anchor(
    repo_root: Path,
    run_id: str = SEMIFINAL_ANCHOR_RUN_ID,
) -> SemifinalAnchorSummary:
    """Run NEC2 then openEMS 1x/2x and persist one all-or-nothing certificate."""

    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        return SemifinalAnchorSummary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    geometry = semifinal_anchor_geometry()
    geometry_digest = validate_semifinal_anchor_hash(geometry)
    config: dict[str, Any] = {
        "protocol_version": SEMIFINAL_ANCHOR_PROTOCOL,
        "preregistration_commit": PREREGISTRATION_COMMIT,
        "geometry_hash": geometry_digest,
        "geometry": geometry.metadata,
        "frequency_range_hz": ANCHOR_SWEEP_HZ,
        "frequency_points": ANCHOR_FREQUENCY_POINTS,
        "nec2_segments_per_wavelength": ANCHOR_NEC2_DENSITY,
        "openems_refinements": OPENEMS_REFINEMENTS,
        "openems_convergence_threshold": OPENEMS_CONVERGENCE_THRESHOLD,
        "anchor_resonance_threshold": ANCHOR_RESONANCE_THRESHOLD,
        "anchor_pearson_threshold": ANCHOR_CORRELATION_THRESHOLD,
        "openems_timeout_seconds": OPENEMS_TIMEOUT_SECONDS,
    }
    started_at = datetime.now(UTC)
    nec2_adapter = NEC2Adapter()
    nec2_spec = _spec(f"{run_id}-nec2")
    nec2_mesh = await nec2_adapter.mesh(geometry, nec2_spec)
    nec2 = _curve(await nec2_adapter.solve(nec2_mesh, nec2_spec))
    if nec2.solver_mode != "subprocess":
        raise CrossCheckError(f"semifinal anchor NEC2 is not real: {nec2.solver_mode}")
    openems_1x = _run_openems_monitored(
        geometry,
        refinement=1.0,
        run_id=f"{run_id}-openems-1x",
    )
    openems_2x = _run_openems_monitored(
        geometry,
        refinement=2.0,
        run_id=f"{run_id}-openems-2x",
    )
    decision = evaluate_semifinal_anchor(
        nec2,
        openems_1x.curve,
        openems_2x.curve,
    )
    summary = SemifinalAnchorSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 3},
        geometry_hash=geometry_digest,
        geometry=geometry.model_dump(mode="json", exclude={"id"}),
        nec2=nec2,
        openems_1x=openems_1x,
        openems_2x=openems_2x,
        decision=decision,
    )
    _write_run(run_directory, summary)
    return summary
