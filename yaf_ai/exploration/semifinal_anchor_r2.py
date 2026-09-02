"""Preregistered r2 qualification of the 5.8 GHz meander renderer."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

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
from yaf_ai.exploration.semifinal_anchor import (
    C0,
    MonitoredOpenEMSResult,
    _run_openems_monitored,
)
from yaf_core.domain.geometry import Geometry
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter

R1_LENGTH_M = 0.0258441774
R1_NEC2_RESONANCE_FREQUENCY_HZ = 5_480_000_000.0
TARGET_FREQUENCY_HZ = 5_800_000_000.0
R2_LENGTH_M = (
    R1_LENGTH_M
    * R1_NEC2_RESONANCE_FREQUENCY_HZ
    / TARGET_FREQUENCY_HZ
)
R2_FEED_GAP_M = 0.000600
R2_WIRE_RADIUS_M = 5e-5
R2_SWEEP_HZ = (1.5e9, 6.5e9)
R2_FREQUENCY_POINTS = 251
R2_NEC2_DENSITY = 40
R2_OPENEMS_REFINEMENTS = (1.0, 2.0, 4.0, 8.0)
R2_CONVERGENCE_THRESHOLD = 0.03
R2_OPENEMS_TIMEOUT_SECONDS = 3600.0
R2_PROTOCOL = "semifinal-wifi58-meander-renderer-anchor-r2"
R2_RUN_ID = f"{R2_PROTOCOL}-combined"
R2_PREREGISTRATION_COMMIT = "7f44ac8"
R2_GEOMETRY_SHA256 = (
    "1c0e018ac1e65aacf30ac158ef2336f461b430036b0c6ad9eb2bfefb15ba0d5a"
)
R1_LOG_SHA256 = (
    "937bd9d53a992a7bfce54d886652291fbac49c366f8fd617d4681f5ff4258b89"
)
R1_SUMMARY_SHA256 = (
    "61d012118b489634f9e04c4c5a02ada6532edbf3e9088f68806376b6b07f68c7"
)

R2Verdict = Literal[
    "not_released_out_of_band",
    "not_released_not_converged",
    "not_released_agreement",
    "released",
]


class OpenEMSRunner(Protocol):
    """Callable boundary used to prove the fixed four-level ladder."""

    def __call__(
        self,
        geometry: Geometry,
        *,
        refinement: float,
        run_id: str,
    ) -> MonitoredOpenEMSResult: ...


class SemifinalAnchorR2Decision(BaseModel):
    """Frozen r2 validity, convergence, agreement, and verdict fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nec2_validity: BandResonanceValidity
    openems_1x_validity: BandResonanceValidity
    openems_2x_validity: BandResonanceValidity
    openems_4x_validity: BandResonanceValidity
    openems_8x_validity: BandResonanceValidity
    cross_solver_decision: AnchorDecision | None
    cross_solver_error: str | None
    openems_4x_to_8x_resonance_shift: float | None = Field(default=None, ge=0.0)
    openems_convergence_threshold: float = R2_CONVERGENCE_THRESHOLD
    openems_convergence_met: bool
    verdict: R2Verdict
    anchor_released: bool


class SemifinalAnchorR2Summary(BaseModel):
    """Archive-compatible certificate containing all five real solves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    run_id: str = R2_RUN_ID
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
    nec2: SolverCurve
    openems_1x: MonitoredOpenEMSResult
    openems_2x: MonitoredOpenEMSResult
    openems_4x: MonitoredOpenEMSResult
    openems_8x: MonitoredOpenEMSResult
    decision: SemifinalAnchorR2Decision


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _minimum_pitch_m(length_m: float) -> float:
    """Reuse the r1 resolution rule while accepting the r2 length input."""

    if length_m <= 0.0:
        raise ValueError("anchor length must be positive")
    return 2.0 * (C0 / TARGET_FREQUENCY_HZ / R2_NEC2_DENSITY)


def semifinal_anchor_r2_geometry() -> Geometry:
    """Build the frozen y-axis anchor through the meander dispatch path."""

    half = R2_LENGTH_M / 2.0
    gap_half = R2_FEED_GAP_M / 2.0
    geometry = Geometry(
        name="semifinal_wifi58_meander_renderer_anchor_r2",
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
            "protocol_version": R2_PROTOCOL,
            "center_frequency_hz": TARGET_FREQUENCY_HZ,
            "length_m": R2_LENGTH_M,
            "feed_gap_m": R2_FEED_GAP_M,
            "wire_radius_m": R2_WIRE_RADIUS_M,
            "minimum_pitch_m": _minimum_pitch_m(R2_LENGTH_M),
            "nec2_extended_thin_wire_kernel": False,
            "edge_order": (
                "feed_gap",
                "positive_arm",
                "negative_arm",
            ),
        },
    )
    validate_semifinal_anchor_r2_geometry(geometry)
    return geometry


def semifinal_anchor_r2_geometry_hash(geometry: Geometry | None = None) -> str:
    """Hash the frozen geometry while excluding its random UUID."""

    source = geometry if geometry is not None else semifinal_anchor_r2_geometry()
    return _canonical_hash(source.model_dump(mode="json", exclude={"id"}))


def validate_semifinal_anchor_r2_geometry(geometry: Geometry) -> str:
    """Reject every preregistered geometry or dispatch deviation."""

    expected_vertices = [
        [0.0, -R2_FEED_GAP_M / 2.0, 0.0],
        [0.0, R2_FEED_GAP_M / 2.0, 0.0],
        [0.0, R2_LENGTH_M / 2.0, 0.0],
        [0.0, -R2_LENGTH_M / 2.0, 0.0],
    ]
    if geometry.vertices != expected_vertices:
        raise CrossCheckError("r2 anchor vertices changed")
    if geometry.faces != [[0, 1], [1, 2], [0, 3]]:
        raise CrossCheckError("r2 anchor edge order changed")
    expected_metadata = (
        "meander_dipole",
        "straight_half_wave",
        R2_PROTOCOL,
        R2_LENGTH_M,
        R2_FEED_GAP_M,
        R2_WIRE_RADIUS_M,
        False,
        ("feed_gap", "positive_arm", "negative_arm"),
    )
    observed_metadata = (
        geometry.metadata.get("antenna_class"),
        geometry.metadata.get("anchor_topology"),
        geometry.metadata.get("protocol_version"),
        geometry.metadata.get("length_m"),
        geometry.metadata.get("feed_gap_m"),
        geometry.metadata.get("wire_radius_m"),
        geometry.metadata.get("nec2_extended_thin_wire_kernel"),
        geometry.metadata.get("edge_order"),
    )
    if observed_metadata != expected_metadata:
        raise CrossCheckError("r2 anchor metadata changed")
    total_length = sum(
        math.dist(geometry.vertices[start], geometry.vertices[stop])
        for start, stop in geometry.faces
    )
    if not math.isclose(total_length, R2_LENGTH_M, rel_tol=0.0, abs_tol=1e-15):
        raise CrossCheckError("r2 anchor conductor length changed")
    digest = semifinal_anchor_r2_geometry_hash(geometry)
    if digest != R2_GEOMETRY_SHA256:
        raise CrossCheckError("r2 anchor geometry SHA-256 changed")
    return digest


def run_openems_ladder(
    geometry: Geometry,
    run_id: str,
    runner: OpenEMSRunner = _run_openems_monitored,
) -> tuple[
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
]:
    """Run the exact four levels without inspecting intermediate results."""

    results = tuple(
        runner(
            geometry,
            refinement=refinement,
            run_id=f"{run_id}-openems-{refinement:g}x",
        )
        for refinement in R2_OPENEMS_REFINEMENTS
    )
    first, second, fourth, eighth = results
    return first, second, fourth, eighth


def _assert_identical_frequency_arrays(curves: tuple[SolverCurve, ...]) -> None:
    reference = curves[0].frequency_hz
    if len(reference) != R2_FREQUENCY_POINTS:
        raise CrossCheckError("r2 anchor frequency-point count changed")
    if any(curve.frequency_hz != reference for curve in curves[1:]):
        raise CrossCheckError("r2 anchor solvers did not use identical frequencies")


def evaluate_semifinal_anchor_r2(
    nec2: SolverCurve,
    openems_1x: SolverCurve,
    openems_2x: SolverCurve,
    openems_4x: SolverCurve,
    openems_8x: SolverCurve,
) -> SemifinalAnchorR2Decision:
    """Apply the four mutually exclusive r2 verdicts in frozen order."""

    _assert_identical_frequency_arrays(
        (nec2, openems_1x, openems_2x, openems_4x, openems_8x)
    )
    nec2_validity = band_validity(nec2, HIGH_BAND_HZ)
    one_validity = band_validity(openems_1x, HIGH_BAND_HZ)
    two_validity = band_validity(openems_2x, HIGH_BAND_HZ)
    four_validity = band_validity(openems_4x, HIGH_BAND_HZ)
    eight_validity = band_validity(openems_8x, HIGH_BAND_HZ)
    shift = high_band_shift(openems_4x, openems_8x)
    convergence_met = shift is not None and shift <= R2_CONVERGENCE_THRESHOLD
    cross_solver: AnchorDecision | None = None
    cross_error: str | None = None
    try:
        evaluated = evaluate_curves(openems_8x, nec2, anchor=True)
        if not isinstance(evaluated, AnchorDecision):
            raise AssertionError("r2 anchor evaluator returned non-anchor decision")
        cross_solver = evaluated
    except CrossCheckError as error:
        cross_error = str(error)

    if not nec2_validity.valid:
        verdict: R2Verdict = "not_released_out_of_band"
    elif not four_validity.valid or not eight_validity.valid or not convergence_met:
        verdict = "not_released_not_converged"
    elif cross_solver is None or cross_solver.verdict != "CONFIRMED":
        verdict = "not_released_agreement"
    else:
        verdict = "released"
    released = verdict == "released"
    return SemifinalAnchorR2Decision(
        nec2_validity=nec2_validity,
        openems_1x_validity=one_validity,
        openems_2x_validity=two_validity,
        openems_4x_validity=four_validity,
        openems_8x_validity=eight_validity,
        cross_solver_decision=cross_solver,
        cross_solver_error=cross_error,
        openems_4x_to_8x_resonance_shift=shift,
        openems_convergence_met=convergence_met,
        verdict=verdict,
        anchor_released=released,
    )


def _write_run(run_directory: Path, summary: SemifinalAnchorR2Summary) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = [
        {
            "schema_version": 1,
            "event_type": "semifinal_anchor_r2_solver_result",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "solver": "nec2",
            "curve": summary.nec2.model_dump(mode="json"),
        }
    ]
    for result in (
        summary.openems_1x,
        summary.openems_2x,
        summary.openems_4x,
        summary.openems_8x,
    ):
        events.append(
            {
                "schema_version": 1,
                "event_type": "semifinal_anchor_r2_solver_result",
                "run_id": summary.run_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "solver": "openems",
                "refinement": result.refinement,
                "result": result.model_dump(mode="json"),
            }
        )
    events.append(
        {
            "schema_version": 1,
            "event_type": "semifinal_anchor_r2_decision",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "decision": summary.decision.model_dump(mode="json"),
        }
    )
    log = "".join(
        json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
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


async def run_semifinal_anchor_r2(
    repo_root: Path,
    run_id: str = R2_RUN_ID,
    *,
    openems_runner: OpenEMSRunner = _run_openems_monitored,
) -> SemifinalAnchorR2Summary:
    """Run NEC2 once and all four fixed openEMS refinements, then persist."""

    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        return SemifinalAnchorR2Summary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    geometry = semifinal_anchor_r2_geometry()
    geometry_hash = validate_semifinal_anchor_r2_geometry(geometry)
    config: dict[str, Any] = {
        "protocol_version": R2_PROTOCOL,
        "preregistration_commit": R2_PREREGISTRATION_COMMIT,
        "geometry_hash": geometry_hash,
        "geometry": geometry.metadata,
        "length_calibration": {
            "r1_length_m": R1_LENGTH_M,
            "r1_nec2_resonance_frequency_hz": R1_NEC2_RESONANCE_FREQUENCY_HZ,
            "target_frequency_hz": TARGET_FREQUENCY_HZ,
            "r2_length_m": R2_LENGTH_M,
        },
        "frequency_range_hz": R2_SWEEP_HZ,
        "frequency_points": R2_FREQUENCY_POINTS,
        "nec2_segments_per_wavelength": R2_NEC2_DENSITY,
        "nec2_extended_thin_wire_kernel": False,
        "openems_refinements": R2_OPENEMS_REFINEMENTS,
        "openems_convergence_pair": (4.0, 8.0),
        "openems_convergence_threshold": R2_CONVERGENCE_THRESHOLD,
        "cross_solver_openems_refinement": 8.0,
        "anchor_resonance_threshold": ANCHOR_RESONANCE_THRESHOLD,
        "anchor_pearson_threshold": ANCHOR_CORRELATION_THRESHOLD,
        "openems_timeout_seconds": R2_OPENEMS_TIMEOUT_SECONDS,
    }
    started_at = datetime.now(UTC)
    adapter = NEC2Adapter()
    from yaf_ai.exploration.semifinal_anchor import _spec

    nec2_spec = _spec(f"{run_id}-nec2")
    nec2_mesh = await adapter.mesh(geometry, nec2_spec)
    nec2 = _curve(await adapter.solve(nec2_mesh, nec2_spec))
    if nec2.solver_mode != "subprocess":
        raise CrossCheckError(f"r2 anchor NEC2 is not real: {nec2.solver_mode}")
    one, two, four, eight = run_openems_ladder(
        geometry,
        run_id,
        runner=openems_runner,
    )
    decision = evaluate_semifinal_anchor_r2(
        nec2,
        one.curve,
        two.curve,
        four.curve,
        eight.curve,
    )
    summary = SemifinalAnchorR2Summary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 5},
        geometry_hash=geometry_hash,
        geometry=geometry.model_dump(mode="json", exclude={"id"}),
        nec2=nec2,
        openems_1x=one,
        openems_2x=two,
        openems_4x=four,
        openems_8x=eight,
        decision=decision,
    )
    _write_run(run_directory, summary)
    return summary
