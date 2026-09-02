"""Bounded r3 extension of the 5.8 GHz meander-renderer certificate."""

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
    DAY6_EDGE_GUARD,
    BandResonanceValidity,
    band_validity,
)
from yaf_ai.exploration.freeform_wire import HIGH_BAND_HZ
from yaf_ai.exploration.semifinal_anchor import (
    MonitoredOpenEMSResult,
    _run_openems_monitored,
    _spec,
)
from yaf_ai.exploration.semifinal_anchor_r2 import (
    R2_FREQUENCY_POINTS,
    R2_GEOMETRY_SHA256,
    R2_RUN_ID,
    R2_SWEEP_HZ,
    SemifinalAnchorR2Summary,
    semifinal_anchor_r2_geometry,
    validate_semifinal_anchor_r2_geometry,
)
from yaf_core.domain.geometry import Geometry
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter

R2_LOG_SHA256 = (
    "8d8387a9859417d6e9f62c07a385ba4d6a89e204e579d6c0359ddeb3b241de2c"
)
R2_SUMMARY_SHA256_FROZEN = (
    "5c0987c439f21147e187cbc630870b57aaea3e6736569d05d28b232fe2dd7871"
)
R3_PROTOCOL = "semifinal-wifi58-meander-renderer-anchor-r3"
R3_RUN_ID = f"{R3_PROTOCOL}-combined"
R3_PREREGISTRATION_COMMIT = "b1e74d9"
R3_OPENEMS_REFINEMENTS = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0)
R3_CONVERGENCE_PAIR = (16.0, 32.0)
R3_AGREEMENT_REFINEMENT = 32.0
R3_CONVERGENCE_THRESHOLD = 0.03
R3_OPENEMS_TIMEOUT_SECONDS = 3600.0
R2_REPRODUCTION_REFINEMENTS = (1.0, 2.0, 4.0, 8.0)

R3Verdict = Literal[
    "released",
    "not_released_out_of_band_high",
    "not_released_agreement",
    "not_released_not_converged",
]
RichardsonStatus = Literal[
    "computed",
    "exact_last_pair_plateau",
    "unavailable",
]


class OpenEMSRunner(Protocol):
    """Callable boundary for the fixed, result-independent ladder."""

    def __call__(
        self,
        geometry: Geometry,
        *,
        refinement: float,
        run_id: str,
    ) -> MonitoredOpenEMSResult: ...


class FullSweepInteriorMinimum(BaseModel):
    """Global full-sweep minimum with only the frozen interior/local gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_index: int = Field(ge=0)
    minimum_frequency_hz: float = Field(gt=0.0)
    minimum_s11_db: float
    local_minimum: bool
    wide_sweep_interior: bool
    valid: bool


class RichardsonEstimate(BaseModel):
    """Descriptive fixed three-level Richardson diagnostic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    refinements: tuple[float, float, float] = (8.0, 16.0, 32.0)
    frequencies_hz: tuple[float, float, float] | None
    first_difference_hz: float | None
    second_difference_hz: float | None
    estimated_order: float | None
    estimated_limit_frequency_hz: float | None
    status: RichardsonStatus
    reason: str | None
    affects_verdict: bool = False


class R2ReproductionComparison(BaseModel):
    """Raw r3-minus-r2 result at one descriptive shared refinement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_run_id: str = R2_RUN_ID
    refinement: float
    r2_resonance_frequency_hz: float
    r3_resonance_frequency_hz: float
    frequency_difference_hz: float
    r2_resonance_s11_db: float
    r3_resonance_s11_db: float
    s11_difference_db: float
    affects_verdict: bool = False


class SemifinalAnchorR3Decision(BaseModel):
    """Only the preregistered terminal-pair and 32x release gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nec2_validity: BandResonanceValidity
    openems_16x_full_sweep_minimum: FullSweepInteriorMinimum
    openems_32x_full_sweep_minimum: FullSweepInteriorMinimum
    openems_32x_validity: BandResonanceValidity
    openems_16x_to_32x_resonance_shift: float | None = Field(default=None, ge=0.0)
    openems_convergence_threshold: float = R3_CONVERGENCE_THRESHOLD
    openems_convergence_met: bool
    cross_solver_decision: AnchorDecision | None
    cross_solver_error: str | None
    verdict: R3Verdict
    anchor_released: bool


class SemifinalAnchorR3Summary(BaseModel):
    """Archive-compatible certificate with all seven real subprocess curves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    run_id: str = R3_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = 7
    evaluation_budget: int = 7
    solver_mode_counts: dict[str, int]
    geometry_hash: str
    geometry: dict[str, Any]
    nec2: SolverCurve
    openems_1x: MonitoredOpenEMSResult
    openems_2x: MonitoredOpenEMSResult
    openems_4x: MonitoredOpenEMSResult
    openems_8x: MonitoredOpenEMSResult
    openems_16x: MonitoredOpenEMSResult
    openems_32x: MonitoredOpenEMSResult
    decision: SemifinalAnchorR3Decision
    richardson_estimate: RichardsonEstimate
    r2_reproduction: tuple[
        R2ReproductionComparison,
        R2ReproductionComparison,
        R2ReproductionComparison,
        R2ReproductionComparison,
    ]


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def run_openems_r3_ladder(
    geometry: Geometry,
    run_id: str,
    runner: OpenEMSRunner = _run_openems_monitored,
) -> tuple[
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
    MonitoredOpenEMSResult,
]:
    """Run every frozen level without inspecting any intermediate result."""

    results = tuple(
        runner(
            geometry,
            refinement=refinement,
            run_id=f"{run_id}-openems-{refinement:g}x",
        )
        for refinement in R3_OPENEMS_REFINEMENTS
    )
    one, two, four, eight, sixteen, thirty_two = results
    return one, two, four, eight, sixteen, thirty_two


def full_sweep_interior_minimum(curve: SolverCurve) -> FullSweepInteriorMinimum:
    """Evaluate the prospective r3 full-sweep internal-minimum definition."""

    if not curve.s11_db or len(curve.frequency_hz) != len(curve.s11_db):
        raise CrossCheckError("r3 curve is empty or has mismatched arrays")
    index = min(range(len(curve.s11_db)), key=curve.s11_db.__getitem__)
    interior = (
        DAY6_EDGE_GUARD
        <= index
        <= len(curve.s11_db) - DAY6_EDGE_GUARD - 1
    )
    local = (
        0 < index < len(curve.s11_db) - 1
        and curve.s11_db[index] <= curve.s11_db[index - 1]
        and curve.s11_db[index] <= curve.s11_db[index + 1]
        and (
            curve.s11_db[index] < curve.s11_db[index - 1]
            or curve.s11_db[index] < curve.s11_db[index + 1]
        )
    )
    return FullSweepInteriorMinimum(
        minimum_index=index,
        minimum_frequency_hz=curve.frequency_hz[index],
        minimum_s11_db=curve.s11_db[index],
        local_minimum=local,
        wide_sweep_interior=interior,
        valid=local and interior,
    )


def full_sweep_shift(
    first: SolverCurve,
    second: SolverCurve,
) -> float | None:
    """Return only the preregistered full-sweep internal-minimum movement."""

    first_minimum = full_sweep_interior_minimum(first)
    second_minimum = full_sweep_interior_minimum(second)
    if not first_minimum.valid or not second_minimum.valid:
        return None
    return abs(
        first_minimum.minimum_frequency_hz - second_minimum.minimum_frequency_hz
    ) / second_minimum.minimum_frequency_hz


def _assert_identical_frequency_arrays(curves: tuple[SolverCurve, ...]) -> None:
    reference = curves[0].frequency_hz
    if len(reference) != R2_FREQUENCY_POINTS:
        raise CrossCheckError("r3 anchor frequency-point count changed")
    if any(curve.frequency_hz != reference for curve in curves[1:]):
        raise CrossCheckError("r3 anchor solvers did not use identical frequencies")


def evaluate_semifinal_anchor_r3(
    nec2: SolverCurve,
    openems_16x: SolverCurve,
    openems_32x: SolverCurve,
) -> SemifinalAnchorR3Decision:
    """Apply only the frozen 16x/32x convergence and NEC2/32x agreement."""

    _assert_identical_frequency_arrays((nec2, openems_16x, openems_32x))
    nec2_validity = band_validity(nec2, HIGH_BAND_HZ)
    sixteen_minimum = full_sweep_interior_minimum(openems_16x)
    thirty_two_minimum = full_sweep_interior_minimum(openems_32x)
    thirty_two_validity = band_validity(openems_32x, HIGH_BAND_HZ)
    shift = full_sweep_shift(openems_16x, openems_32x)
    convergence_met = shift is not None and shift <= R3_CONVERGENCE_THRESHOLD
    cross_solver: AnchorDecision | None = None
    cross_error: str | None = None
    try:
        evaluated = evaluate_curves(openems_32x, nec2, anchor=True)
        if not isinstance(evaluated, AnchorDecision):
            raise AssertionError("r3 anchor evaluator returned non-anchor decision")
        cross_solver = evaluated
    except CrossCheckError as error:
        cross_error = str(error)

    if not convergence_met:
        verdict: R3Verdict = "not_released_not_converged"
    elif thirty_two_minimum.minimum_frequency_hz > HIGH_BAND_HZ[1]:
        verdict = "not_released_out_of_band_high"
    elif (
        not nec2_validity.valid
        or not thirty_two_validity.valid
        or cross_solver is None
        or cross_solver.verdict != "CONFIRMED"
    ):
        verdict = "not_released_agreement"
    else:
        verdict = "released"
    return SemifinalAnchorR3Decision(
        nec2_validity=nec2_validity,
        openems_16x_full_sweep_minimum=sixteen_minimum,
        openems_32x_full_sweep_minimum=thirty_two_minimum,
        openems_32x_validity=thirty_two_validity,
        openems_16x_to_32x_resonance_shift=shift,
        openems_convergence_met=convergence_met,
        cross_solver_decision=cross_solver,
        cross_solver_error=cross_error,
        verdict=verdict,
        anchor_released=verdict == "released",
    )


def richardson_estimate(
    openems_8x: SolverCurve,
    openems_16x: SolverCurve,
    openems_32x: SolverCurve,
) -> RichardsonEstimate:
    """Apply the frozen descriptive 8x/16x/32x Richardson formula."""

    minima = tuple(
        full_sweep_interior_minimum(curve)
        for curve in (openems_8x, openems_16x, openems_32x)
    )
    if not all(minimum.valid for minimum in minima):
        return RichardsonEstimate(
            frequencies_hz=None,
            first_difference_hz=None,
            second_difference_hz=None,
            estimated_order=None,
            estimated_limit_frequency_hz=None,
            status="unavailable",
            reason="one or more finest-three curves lack a full-sweep internal minimum",
        )
    frequencies = tuple(minimum.minimum_frequency_hz for minimum in minima)
    first_difference = frequencies[1] - frequencies[0]
    second_difference = frequencies[2] - frequencies[1]
    if second_difference == 0.0:
        return RichardsonEstimate(
            frequencies_hz=frequencies,
            first_difference_hz=first_difference,
            second_difference_hz=second_difference,
            estimated_order=None,
            estimated_limit_frequency_hz=frequencies[2],
            status="exact_last_pair_plateau",
            reason=None,
        )
    same_direction = first_difference * second_difference > 0.0
    ratio = abs(first_difference / second_difference)
    if not same_direction or ratio <= 1.0:
        return RichardsonEstimate(
            frequencies_hz=frequencies,
            first_difference_hz=first_difference,
            second_difference_hz=second_difference,
            estimated_order=None,
            estimated_limit_frequency_hz=None,
            status="unavailable",
            reason="differences are not same-sign and geometrically decaying",
        )
    order = math.log2(ratio)
    limit = frequencies[2] + second_difference / (2.0**order - 1.0)
    return RichardsonEstimate(
        frequencies_hz=frequencies,
        first_difference_hz=first_difference,
        second_difference_hz=second_difference,
        estimated_order=order,
        estimated_limit_frequency_hz=limit,
        status="computed",
        reason=None,
    )


def compare_with_r2(
    r2: SemifinalAnchorR2Summary,
    r3_results: tuple[
        MonitoredOpenEMSResult,
        MonitoredOpenEMSResult,
        MonitoredOpenEMSResult,
        MonitoredOpenEMSResult,
    ],
) -> tuple[
    R2ReproductionComparison,
    R2ReproductionComparison,
    R2ReproductionComparison,
    R2ReproductionComparison,
]:
    """Record raw shared-level differences without a pass/fail decision."""

    r2_results = (
        r2.openems_1x,
        r2.openems_2x,
        r2.openems_4x,
        r2.openems_8x,
    )
    rows: list[R2ReproductionComparison] = []
    for refinement, old, new in zip(
        R2_REPRODUCTION_REFINEMENTS,
        r2_results,
        r3_results,
        strict=True,
    ):
        rows.append(
            R2ReproductionComparison(
                refinement=refinement,
                r2_resonance_frequency_hz=old.curve.resonance_frequency_hz,
                r3_resonance_frequency_hz=new.curve.resonance_frequency_hz,
                frequency_difference_hz=(
                    new.curve.resonance_frequency_hz
                    - old.curve.resonance_frequency_hz
                ),
                r2_resonance_s11_db=old.curve.resonance_s11_db,
                r3_resonance_s11_db=new.curve.resonance_s11_db,
                s11_difference_db=(
                    new.curve.resonance_s11_db - old.curve.resonance_s11_db
                ),
            )
        )
    first, second, fourth, eighth = rows
    return first, second, fourth, eighth


def _load_r2_summary(repo_root: Path) -> SemifinalAnchorR2Summary:
    path = repo_root / "artifacts" / "runs" / R2_RUN_ID / "summary.json"
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != R2_SUMMARY_SHA256_FROZEN:
        raise CrossCheckError("archived r2 summary SHA-256 changed")
    return SemifinalAnchorR2Summary.model_validate_json(payload)


def _write_run(run_directory: Path, summary: SemifinalAnchorR3Summary) -> None:
    run_directory.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = [
        {
            "schema_version": 1,
            "event_type": "semifinal_anchor_r3_solver_result",
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
        summary.openems_16x,
        summary.openems_32x,
    ):
        events.append(
            {
                "schema_version": 1,
                "event_type": "semifinal_anchor_r3_solver_result",
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
            "event_type": "semifinal_anchor_r3_decision",
            "run_id": summary.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "decision": summary.decision.model_dump(mode="json"),
            "richardson_estimate": summary.richardson_estimate.model_dump(mode="json"),
            "r2_reproduction": [
                row.model_dump(mode="json") for row in summary.r2_reproduction
            ],
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


async def run_semifinal_anchor_r3(
    repo_root: Path,
    run_id: str = R3_RUN_ID,
    *,
    openems_runner: OpenEMSRunner = _run_openems_monitored,
) -> SemifinalAnchorR3Summary:
    """Run one NEC2 and the unconditional six-level openEMS ladder."""

    run_directory = repo_root / "runs" / run_id
    if run_directory.exists():
        return SemifinalAnchorR3Summary.model_validate_json(
            (run_directory / "summary.json").read_text(encoding="utf-8")
        )
    geometry = semifinal_anchor_r2_geometry()
    geometry_hash = validate_semifinal_anchor_r2_geometry(geometry)
    if geometry_hash != R2_GEOMETRY_SHA256:
        raise CrossCheckError("r3 did not reuse the exact r2 geometry")
    r2_summary = _load_r2_summary(repo_root)
    config: dict[str, Any] = {
        "protocol_version": R3_PROTOCOL,
        "preregistration_commit": R3_PREREGISTRATION_COMMIT,
        "geometry_source_protocol": r2_summary.config["protocol_version"],
        "geometry_hash": geometry_hash,
        "geometry": geometry.metadata,
        "frequency_range_hz": R2_SWEEP_HZ,
        "frequency_points": R2_FREQUENCY_POINTS,
        "nec2_segments_per_wavelength": r2_summary.config[
            "nec2_segments_per_wavelength"
        ],
        "nec2_extended_thin_wire_kernel": False,
        "openems_refinements": R3_OPENEMS_REFINEMENTS,
        "openems_convergence_pair": R3_CONVERGENCE_PAIR,
        "openems_convergence_definition": "full_sweep_internal_minimum",
        "openems_convergence_threshold": R3_CONVERGENCE_THRESHOLD,
        "cross_solver_openems_refinement": R3_AGREEMENT_REFINEMENT,
        "anchor_resonance_threshold": ANCHOR_RESONANCE_THRESHOLD,
        "anchor_pearson_threshold": ANCHOR_CORRELATION_THRESHOLD,
        "openems_timeout_seconds": R3_OPENEMS_TIMEOUT_SECONDS,
        "r2_reproduction_source_run_id": R2_RUN_ID,
    }
    started_at = datetime.now(UTC)
    adapter = NEC2Adapter()
    nec2_spec = _spec(f"{run_id}-nec2")
    nec2_mesh = await adapter.mesh(geometry, nec2_spec)
    nec2 = _curve(await adapter.solve(nec2_mesh, nec2_spec))
    if nec2.solver_mode != "subprocess":
        raise CrossCheckError(f"r3 anchor NEC2 is not real: {nec2.solver_mode}")
    one, two, four, eight, sixteen, thirty_two = run_openems_r3_ladder(
        geometry,
        run_id,
        runner=openems_runner,
    )
    all_curves = (
        nec2,
        one.curve,
        two.curve,
        four.curve,
        eight.curve,
        sixteen.curve,
        thirty_two.curve,
    )
    _assert_identical_frequency_arrays(all_curves)
    decision = evaluate_semifinal_anchor_r3(nec2, sixteen.curve, thirty_two.curve)
    richardson = richardson_estimate(eight.curve, sixteen.curve, thirty_two.curve)
    reproduction = compare_with_r2(r2_summary, (one, two, four, eight))
    summary = SemifinalAnchorR3Summary(
        run_id=run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=_canonical_hash(config),
        config=config,
        solver_mode_counts={"subprocess": 7},
        geometry_hash=geometry_hash,
        geometry=geometry.model_dump(mode="json", exclude={"id"}),
        nec2=nec2,
        openems_1x=one,
        openems_2x=two,
        openems_4x=four,
        openems_8x=eight,
        openems_16x=sixteen,
        openems_32x=thirty_two,
        decision=decision,
        richardson_estimate=richardson,
        r2_reproduction=reproduction,
    )
    _write_run(run_directory, summary)
    return summary
