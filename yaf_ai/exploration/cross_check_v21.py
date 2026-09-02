"""Protocol v2.1 resonance-validity gate for native wire cross-checks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.cross_check import SolverCurve
from yaf_ai.exploration.cross_check_v2 import evaluate_curves

PROTOCOL_VERSION: Literal["day4-wideband-resonance-v2.1"] = (
    "day4-wideband-resonance-v2.1"
)
WIDEBAND_FREQUENCY_RANGE_HZ = (1.5e9, 3.5e9)
WIDEBAND_FREQUENCY_POINTS = 201
RESONANCE_DEPTH_THRESHOLD_DB = -6.0
EDGE_GUARD_SAMPLE_COUNT = 3

CurveVerdictV21 = Literal[
    "CONFIRMED",
    "DIVERGENT",
    "NO_RESONANCE_IN_BAND",
]


class ResonanceValidity(BaseModel):
    """Per-solver prerequisite applied before agreement metrics."""

    model_config = ConfigDict(frozen=True)

    minimum_index: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    minimum_frequency_hz: float = Field(gt=0.0)
    minimum_s11_db: float
    interior_minimum: bool
    depth_threshold_db: float = RESONANCE_DEPTH_THRESHOLD_DB
    depth_threshold_met: bool
    valid: bool


class CurveDecisionV21(BaseModel):
    """Protocol-v2.1 result, including failures before solver agreement."""

    model_config = ConfigDict(frozen=True)

    protocol_version: Literal["day4-wideband-resonance-v2.1"] = PROTOCOL_VERSION
    openems_validity: ResonanceValidity
    nec2_validity: ResonanceValidity
    resonance_relative_difference: float | None = Field(default=None, ge=0.0)
    resonance_threshold: float = 0.05
    resonance_threshold_met: bool | None = None
    curve_pearson_correlation: float | None = Field(default=None, ge=-1.0, le=1.0)
    curve_correlation_threshold: float = 0.8
    curve_correlation_threshold_met: bool | None = None
    s11_depth_difference_db: float | None = Field(default=None, ge=0.0)
    s11_depth_is_record_only: bool = True
    verdict: CurveVerdictV21


def resonance_validity(curve: SolverCurve) -> ResonanceValidity:
    """Check that a sampled curve contains a deep interior minimum."""

    if len(curve.frequency_hz) != len(curve.s11_db) or not curve.s11_db:
        raise ValueError("solver curve frequency and S11 samples must align")
    minimum_index = min(range(len(curve.s11_db)), key=curve.s11_db.__getitem__)
    sample_count = len(curve.s11_db)
    interior = (
        EDGE_GUARD_SAMPLE_COUNT
        <= minimum_index
        <= sample_count - EDGE_GUARD_SAMPLE_COUNT - 1
    )
    depth_met = curve.s11_db[minimum_index] <= RESONANCE_DEPTH_THRESHOLD_DB
    return ResonanceValidity(
        minimum_index=minimum_index,
        sample_count=sample_count,
        minimum_frequency_hz=curve.frequency_hz[minimum_index],
        minimum_s11_db=curve.s11_db[minimum_index],
        interior_minimum=interior,
        depth_threshold_met=depth_met,
        valid=interior and depth_met,
    )


def evaluate_curves_v21(
    openems: SolverCurve,
    nec2: SolverCurve,
) -> CurveDecisionV21:
    """Apply resonance validity, then inherit v2 agreement thresholds."""

    openems_validity = resonance_validity(openems)
    nec2_validity = resonance_validity(nec2)
    if not openems_validity.valid or not nec2_validity.valid:
        return CurveDecisionV21(
            openems_validity=openems_validity,
            nec2_validity=nec2_validity,
            verdict="NO_RESONANCE_IN_BAND",
        )
    inherited = evaluate_curves(openems, nec2)
    return CurveDecisionV21(
        openems_validity=openems_validity,
        nec2_validity=nec2_validity,
        resonance_relative_difference=inherited.resonance_relative_difference,
        resonance_threshold=inherited.resonance_threshold,
        resonance_threshold_met=inherited.resonance_threshold_met,
        curve_pearson_correlation=inherited.curve_pearson_correlation,
        curve_correlation_threshold=inherited.curve_correlation_threshold,
        curve_correlation_threshold_met=inherited.curve_correlation_threshold_met,
        s11_depth_difference_db=inherited.s11_depth_difference_db,
        verdict=inherited.verdict,
    )
