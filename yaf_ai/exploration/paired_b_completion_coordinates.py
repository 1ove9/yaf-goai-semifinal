"""Exact two-dimensional A-only support for frozen B-parent completion."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from fractions import Fraction
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_feasible_coordinates import (
    SPAN_BOUNDS,
    STATE_A_LENGTH_BOUNDS,
    exact_nominal_failure_reason,
)
from yaf_ai.exploration.paired_meander import (
    TRAJECTORY_POINT_COUNT,
    HardwareSpec,
    PairedProposal,
    StateControl,
    audit_trajectory,
    build_state_geometry,
    hardware_hash,
    state_geometry_hash,
)

MAPPING_VERSION = "b-parent-a-only-exact-support-v1"
A_ONLY_VECTOR_DIMENSIONS = 2
CERTIFICATE_EXPECTED_SPANS_PER_PARENT = SPAN_BOUNDS[1] - SPAN_BOUNDS[0] + 1
CERTIFICATE_EXPECTED_SPANS = 2 * CERTIFICATE_EXPECTED_SPANS_PER_PARENT

ParentID = Literal["p01", "p02"]
CertificateStatus = Literal["passed", "failed", "incomplete"]
CertificateFailureClass = Literal[
    "parent_identity_failed",
    "suffix_precondition_failed",
    "upper_not_legal",
    "lower_not_legal",
    "lower_predecessor_legal",
    "lower_round_trip_failed",
    "upper_round_trip_failed",
    "lower_exact_audit_disagreement",
    "upper_exact_audit_disagreement",
]

CERTIFICATE_FAILURE_ORDER: tuple[CertificateFailureClass, ...] = (
    "parent_identity_failed",
    "suffix_precondition_failed",
    "upper_not_legal",
    "lower_not_legal",
    "lower_predecessor_legal",
    "lower_round_trip_failed",
    "upper_round_trip_failed",
    "lower_exact_audit_disagreement",
    "upper_exact_audit_disagreement",
)


class BCompletionCoordinateInvariantError(ValueError):
    """Raised when the preregistered exact-support map cannot be satisfied."""


class FrozenBParent(BaseModel):
    """One source-addressed hardware and state-B identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: ParentID
    parent_code: int = Field(ge=1, le=2)
    hardware: HardwareSpec
    state_b: StateControl
    expected_hardware_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_state_b_geometry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_frozen_identity(self) -> Self:
        """Require the constants to reconstruct the preregistered hashes."""

        expected_code = 1 if self.parent_id == "p01" else 2
        if self.parent_code != expected_code:
            raise ValueError("parent code differs from its frozen parent ID")
        if self.state_b.state != "B":
            raise ValueError("frozen parent control must be state B")
        if hardware_hash(self.hardware) != self.expected_hardware_hash:
            raise ValueError("frozen parent hardware hash does not reconstruct")
        geometry = build_state_geometry(self.hardware, self.state_b)
        if (
            state_geometry_hash(self.hardware, self.state_b, geometry)
            != self.expected_state_b_geometry_hash
        ):
            raise ValueError("frozen parent state-B geometry hash does not reconstruct")
        return self


P01 = FrozenBParent(
    parent_id="p01",
    parent_code=1,
    hardware=HardwareSpec(
        turn_count=3,
        feed_gap_ratio_ppm=49_001,
        terminal_ratio_ppm=0,
    ),
    state_b=StateControl(
        state="B",
        total_wire_length_um=26_090,
        span_ratio_ppm=785_552,
    ),
    expected_hardware_hash=(
        "52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b"
    ),
    expected_state_b_geometry_hash=(
        "c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1"
    ),
)
P02 = FrozenBParent(
    parent_id="p02",
    parent_code=2,
    hardware=HardwareSpec(
        turn_count=3,
        feed_gap_ratio_ppm=48_021,
        terminal_ratio_ppm=0,
    ),
    state_b=StateControl(
        state="B",
        total_wire_length_um=26_646,
        span_ratio_ppm=770_570,
    ),
    expected_hardware_hash=(
        "2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1"
    ),
    expected_state_b_geometry_hash=(
        "dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d"
    ),
)
FROZEN_B_PARENTS: tuple[FrozenBParent, ...] = (P01, P02)


def get_frozen_parent(parent_id: ParentID) -> FrozenBParent:
    """Return one immutable B parent by its preregistered ID."""

    if parent_id == "p01":
        return P01
    if parent_id == "p02":
        return P02
    raise BCompletionCoordinateInvariantError("unknown frozen B-parent ID")


def _validated_bounds(bounds: tuple[int, int]) -> tuple[int, int]:
    lower, upper = bounds
    if lower > upper:
        raise BCompletionCoordinateInvariantError("integer bounds are reversed")
    return lower, upper


def half_up_map(value: float, bounds: tuple[int, int]) -> int:
    """Map one binary64 coordinate to an inclusive integer interval."""

    lower, upper = _validated_bounds(bounds)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise BCompletionCoordinateInvariantError(
            "normalized coordinate must be finite in [0,1]"
        )
    mapped = lower + value * (upper - lower)
    return min(upper, max(lower, math.floor(mapped + 0.5)))


def canonical_inverse(value: int, bounds: tuple[int, int]) -> float:
    """Return the exact-Fraction binary64 preimage of one quantized integer."""

    lower, upper = _validated_bounds(bounds)
    if not lower <= value <= upper:
        raise BCompletionCoordinateInvariantError(
            "integer value lies outside its inverse interval"
        )
    coordinate = 0.5 if lower == upper else float(Fraction(value - lower, upper - lower))
    if half_up_map(coordinate, bounds) != value:
        raise BCompletionCoordinateInvariantError("canonical inverse failed to round trip")
    return coordinate


def interpolate_integer(start: int, end: int, index: int) -> int:
    """Interpolate one actuator integer on the frozen 21-point trajectory."""

    if not 0 <= index < TRAJECTORY_POINT_COUNT:
        raise BCompletionCoordinateInvariantError(
            "trajectory index must lie in [0,20]"
        )
    denominator = TRAJECTORY_POINT_COUNT - 1
    return ((denominator - index) * start + index * end + denominator // 2) // denominator


def _normalized(values: Sequence[float]) -> tuple[float, float]:
    if len(values) != A_ONLY_VECTOR_DIMENSIONS:
        raise BCompletionCoordinateInvariantError(
            "A-only proposal vector must have exactly two dimensions"
        )
    first = float(values[0])
    second = float(values[1])
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in (first, second)):
        raise BCompletionCoordinateInvariantError(
            "A-only coordinates must be finite in [0,1]"
        )
    return first, second


def exact_a_only_failure_reason(
    parent: FrozenBParent,
    *,
    state_a_length_um: int,
    state_a_span_ppm: int,
) -> str | None:
    """Apply the unchanged exact nominal predicate to one fixed-B pair."""

    return exact_nominal_failure_reason(
        turn_count=parent.hardware.turn_count,
        feed_gap_ratio_ppm=parent.hardware.feed_gap_ratio_ppm,
        terminal_ratio_ppm=parent.hardware.terminal_ratio_ppm,
        state_a_length_um=state_a_length_um,
        state_a_span_ppm=state_a_span_ppm,
        state_b_length_um=parent.state_b.total_wire_length_um,
        state_b_span_ppm=parent.state_b.span_ratio_ppm,
    )


def is_exact_a_only_legal(
    parent: FrozenBParent,
    *,
    state_a_length_um: int,
    state_a_span_ppm: int,
) -> bool:
    """Return whether one A control belongs to the frozen exact support."""

    return (
        exact_a_only_failure_reason(
            parent,
            state_a_length_um=state_a_length_um,
            state_a_span_ppm=state_a_span_ppm,
        )
        is None
    )


def suffix_preconditions_hold(parent: FrozenBParent, state_a_span_ppm: int) -> bool:
    """Check the frozen monotone-suffix premises used by lower-bound search."""

    if not SPAN_BOUNDS[0] <= state_a_span_ppm <= SPAN_BOUNDS[1]:
        return False
    if parent.hardware.turn_count <= 0:
        return False
    for index in range(TRAJECTORY_POINT_COUNT):
        lower_length = interpolate_integer(
            STATE_A_LENGTH_BOUNDS[0],
            parent.state_b.total_wire_length_um,
            index,
        )
        upper_length = interpolate_integer(
            STATE_A_LENGTH_BOUNDS[1],
            parent.state_b.total_wire_length_um,
            index,
        )
        if lower_length > upper_length:
            return False
        # The interpolated span, and therefore pitch, has no length input.
        interpolate_integer(
            state_a_span_ppm,
            parent.state_b.span_ratio_ppm,
            index,
        )
    return True


def minimum_legal_a_length(parent: FrozenBParent, state_a_span_ppm: int) -> int:
    """Find the first legal A length with the frozen deterministic binary search."""

    if not suffix_preconditions_hold(parent, state_a_span_ppm):
        raise BCompletionCoordinateInvariantError(
            "lower-bound suffix preconditions are not satisfied"
        )
    lower, upper = STATE_A_LENGTH_BOUNDS
    if not is_exact_a_only_legal(
        parent,
        state_a_length_um=upper,
        state_a_span_ppm=state_a_span_ppm,
    ):
        raise BCompletionCoordinateInvariantError(
            "A-only conditional length interval is empty"
        )
    left = lower
    right = upper
    while left < right:
        middle = (left + right) // 2
        if is_exact_a_only_legal(
            parent,
            state_a_length_um=middle,
            state_a_span_ppm=state_a_span_ppm,
        ):
            right = middle
        else:
            left = middle + 1
    return left


def _proposal(
    parent: FrozenBParent,
    *,
    state_a_length_um: int,
    state_a_span_ppm: int,
    proposer: str,
) -> PairedProposal:
    return PairedProposal(
        hardware=parent.hardware,
        state_a=StateControl(
            state="A",
            total_wire_length_um=state_a_length_um,
            span_ratio_ppm=state_a_span_ppm,
        ),
        state_b=parent.state_b,
        proposer=proposer,
    )


def _parent_identity_matches(parent: FrozenBParent, proposal: PairedProposal) -> bool:
    if proposal.hardware != parent.hardware or proposal.state_b != parent.state_b:
        return False
    if hardware_hash(proposal.hardware) != parent.expected_hardware_hash:
        return False
    geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
    return (
        state_geometry_hash(proposal.hardware, proposal.state_b, geometry_b)
        == parent.expected_state_b_geometry_hash
    )


def decode_a_only_coordinates(
    parent: FrozenBParent,
    values: Sequence[float],
    proposer: str,
) -> PairedProposal:
    """Decode one total two-dimensional point while preserving hardware and B."""

    span_raw, length_raw = _normalized(values)
    state_a_span_ppm = half_up_map(span_raw, SPAN_BOUNDS)
    minimum_length = minimum_legal_a_length(parent, state_a_span_ppm)
    state_a_length_um = half_up_map(
        length_raw,
        (minimum_length, STATE_A_LENGTH_BOUNDS[1]),
    )
    proposal = _proposal(
        parent,
        state_a_length_um=state_a_length_um,
        state_a_span_ppm=state_a_span_ppm,
        proposer=proposer,
    )
    reason = exact_a_only_failure_reason(
        parent,
        state_a_length_um=state_a_length_um,
        state_a_span_ppm=state_a_span_ppm,
    )
    if reason is not None:
        raise BCompletionCoordinateInvariantError(reason)
    trajectory = audit_trajectory(proposal)
    if not trajectory.valid:
        raise BCompletionCoordinateInvariantError(
            f"binary64 trajectory audit failed: {trajectory.rejection_reason}"
        )
    if not _parent_identity_matches(parent, proposal):
        raise BCompletionCoordinateInvariantError(
            "decoded proposal changed frozen hardware or state B"
        )
    return proposal


def encode_a_only_coordinates(
    parent: FrozenBParent,
    proposal: PairedProposal,
) -> tuple[float, float]:
    """Return the canonical two-coordinate preimage of one legal fixed-B pair."""

    if not _parent_identity_matches(parent, proposal):
        raise BCompletionCoordinateInvariantError(
            "proposal does not belong to the frozen B parent"
        )
    minimum_length = minimum_legal_a_length(
        parent,
        proposal.state_a.span_ratio_ppm,
    )
    vector = (
        canonical_inverse(proposal.state_a.span_ratio_ppm, SPAN_BOUNDS),
        canonical_inverse(
            proposal.state_a.total_wire_length_um,
            (minimum_length, STATE_A_LENGTH_BOUNDS[1]),
        ),
    )
    decoded = decode_a_only_coordinates(parent, vector, proposal.proposer)
    if decoded != proposal:
        raise BCompletionCoordinateInvariantError(
            "canonical A-only proposal round trip changed bytes"
        )
    return vector


class CertificateFailureWitness(BaseModel):
    """First source-addressable witness for one certificate failure class."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_class: CertificateFailureClass
    span_ratio_ppm: int = Field(ge=SPAN_BOUNDS[0], le=SPAN_BOUNDS[1])
    length_um: int | None = Field(default=None, ge=STATE_A_LENGTH_BOUNDS[0])
    exact_legal: bool | None = None
    audit_legal: bool | None = None
    detail: str = Field(min_length=1)


class CertificateSpanResult(BaseModel):
    """All frozen checks for one parent and one integer A span."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: ParentID
    span_ratio_ppm: int = Field(ge=SPAN_BOUNDS[0], le=SPAN_BOUNDS[1])
    lower_legal_length_um: int | None = Field(
        default=None,
        ge=STATE_A_LENGTH_BOUNDS[0],
        le=STATE_A_LENGTH_BOUNDS[1],
    )
    upper_legal_length_um: int = STATE_A_LENGTH_BOUNDS[1]
    failures: tuple[CertificateFailureWitness, ...] = ()

    @model_validator(mode="after")
    def validate_failure_order(self) -> Self:
        classes = tuple(item.failure_class for item in self.failures)
        if len(classes) != len(set(classes)):
            raise ValueError("certificate span contains duplicate failure classes")
        ordered = tuple(item for item in CERTIFICATE_FAILURE_ORDER if item in classes)
        if classes != ordered:
            raise ValueError("certificate span failure classes are out of frozen order")
        if any(item.span_ratio_ppm != self.span_ratio_ppm for item in self.failures):
            raise ValueError("certificate failure witness names another span")
        return self

    @property
    def passed(self) -> bool:
        return not self.failures


def _certificate_witness(
    failure_class: CertificateFailureClass,
    span_ratio_ppm: int,
    detail: str,
    *,
    length_um: int | None = None,
    exact_legal: bool | None = None,
    audit_legal: bool | None = None,
) -> CertificateFailureWitness:
    return CertificateFailureWitness(
        failure_class=failure_class,
        span_ratio_ppm=span_ratio_ppm,
        length_um=length_um,
        exact_legal=exact_legal,
        audit_legal=audit_legal,
        detail=detail,
    )


def _boundary_audit(
    parent: FrozenBParent,
    span_ratio_ppm: int,
    length_um: int,
) -> tuple[bool, bool]:
    exact_legal = is_exact_a_only_legal(
        parent,
        state_a_length_um=length_um,
        state_a_span_ppm=span_ratio_ppm,
    )
    proposal = _proposal(
        parent,
        state_a_length_um=length_um,
        state_a_span_ppm=span_ratio_ppm,
        proposer="certificate",
    )
    return exact_legal, audit_trajectory(proposal).valid


def evaluate_certificate_span(
    parent: FrozenBParent,
    state_a_span_ppm: int,
) -> CertificateSpanResult:
    """Evaluate all preregistered certificate checks for one integer span."""

    if not SPAN_BOUNDS[0] <= state_a_span_ppm <= SPAN_BOUNDS[1]:
        raise BCompletionCoordinateInvariantError("certificate span lies outside bounds")
    failures: list[CertificateFailureWitness] = []
    if not _parent_identity_matches(
        parent,
        _proposal(
            parent,
            state_a_length_um=STATE_A_LENGTH_BOUNDS[1],
            state_a_span_ppm=state_a_span_ppm,
            proposer="certificate",
        ),
    ):
        failures.append(
            _certificate_witness(
                "parent_identity_failed",
                state_a_span_ppm,
                "frozen hardware or state-B identity did not reconstruct",
            )
        )
    suffix_valid = suffix_preconditions_hold(parent, state_a_span_ppm)
    if not suffix_valid:
        failures.append(
            _certificate_witness(
                "suffix_precondition_failed",
                state_a_span_ppm,
                "monotone lower-bound suffix preconditions did not hold",
            )
        )

    upper = STATE_A_LENGTH_BOUNDS[1]
    upper_exact, upper_audit = _boundary_audit(parent, state_a_span_ppm, upper)
    if not upper_exact:
        failures.append(
            _certificate_witness(
                "upper_not_legal",
                state_a_span_ppm,
                "the frozen upper A-length endpoint is not exact-legal",
                length_um=upper,
                exact_legal=upper_exact,
                audit_legal=upper_audit,
            )
        )

    lower: int | None = None
    if suffix_valid and upper_exact:
        lower = minimum_legal_a_length(parent, state_a_span_ppm)
        lower_exact, lower_audit = _boundary_audit(
            parent,
            state_a_span_ppm,
            lower,
        )
        if not lower_exact:
            failures.append(
                _certificate_witness(
                    "lower_not_legal",
                    state_a_span_ppm,
                    "binary-search lower endpoint is not exact-legal",
                    length_um=lower,
                    exact_legal=lower_exact,
                    audit_legal=lower_audit,
                )
            )
        predecessor = lower - 1
        if predecessor >= STATE_A_LENGTH_BOUNDS[0] and is_exact_a_only_legal(
            parent,
            state_a_length_um=predecessor,
            state_a_span_ppm=state_a_span_ppm,
        ):
            failures.append(
                _certificate_witness(
                    "lower_predecessor_legal",
                    state_a_span_ppm,
                    "the integer immediately below the lower bound is legal",
                    length_um=predecessor,
                    exact_legal=True,
                )
            )
        try:
            lower_raw = canonical_inverse(lower, (lower, upper))
            lower_round_trip = half_up_map(lower_raw, (lower, upper)) == lower
        except BCompletionCoordinateInvariantError:
            lower_round_trip = False
        if not lower_round_trip:
            failures.append(
                _certificate_witness(
                    "lower_round_trip_failed",
                    state_a_span_ppm,
                    "lower endpoint failed its canonical inverse round trip",
                    length_um=lower,
                )
            )
        if lower_exact != lower_audit:
            failures.append(
                _certificate_witness(
                    "lower_exact_audit_disagreement",
                    state_a_span_ppm,
                    "exact and binary64 audits disagree at the lower endpoint",
                    length_um=lower,
                    exact_legal=lower_exact,
                    audit_legal=lower_audit,
                )
            )

    try:
        upper_lower = upper if lower is None else lower
        upper_raw = canonical_inverse(upper, (upper_lower, upper))
        upper_round_trip = half_up_map(upper_raw, (upper_lower, upper)) == upper
    except BCompletionCoordinateInvariantError:
        upper_round_trip = False
    if not upper_round_trip:
        failures.append(
            _certificate_witness(
                "upper_round_trip_failed",
                state_a_span_ppm,
                "upper endpoint failed its canonical inverse round trip",
                length_um=upper,
            )
        )
    if upper_exact != upper_audit:
        failures.append(
            _certificate_witness(
                "upper_exact_audit_disagreement",
                state_a_span_ppm,
                "exact and binary64 audits disagree at the upper endpoint",
                length_um=upper,
                exact_legal=upper_exact,
                audit_legal=upper_audit,
            )
        )
    ordered_failures = tuple(
        next(item for item in failures if item.failure_class == failure_class)
        for failure_class in CERTIFICATE_FAILURE_ORDER
        if any(item.failure_class == failure_class for item in failures)
    )
    return CertificateSpanResult(
        parent_id=parent.parent_id,
        span_ratio_ppm=state_a_span_ppm,
        lower_legal_length_um=lower,
        failures=ordered_failures,
    )


class CertificateFailureTally(BaseModel):
    """Count and first witness for one failure class."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_class: CertificateFailureClass
    count: int = Field(gt=0)
    first_witness: CertificateFailureWitness

    @model_validator(mode="after")
    def validate_witness_class(self) -> Self:
        if self.first_witness.failure_class != self.failure_class:
            raise ValueError("certificate tally witness has another failure class")
        return self


class ParentCertificateStatistics(BaseModel):
    """Streaming aggregate for one complete or partial parent traversal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: ParentID
    expected_span_count: int = CERTIFICATE_EXPECTED_SPANS_PER_PARENT
    checked_span_count: int = Field(ge=0, le=CERTIFICATE_EXPECTED_SPANS_PER_PARENT)
    failed_span_count: int = Field(ge=0)
    failure_tallies: tuple[CertificateFailureTally, ...]
    status: CertificateStatus

    @model_validator(mode="after")
    def validate_statistics(self) -> Self:
        if self.failed_span_count > self.checked_span_count:
            raise ValueError("failed span count exceeds checked span count")
        classes = tuple(item.failure_class for item in self.failure_tallies)
        ordered = tuple(item for item in CERTIFICATE_FAILURE_ORDER if item in classes)
        if classes != ordered or len(classes) != len(set(classes)):
            raise ValueError("certificate tallies are duplicated or out of order")
        expected_status: CertificateStatus
        if self.checked_span_count != self.expected_span_count:
            expected_status = "incomplete"
        elif self.failed_span_count:
            expected_status = "failed"
        else:
            expected_status = "passed"
        if self.status != expected_status:
            raise ValueError("parent certificate status disagrees with its counts")
        return self


def summarize_parent_certificate(
    parent: FrozenBParent,
    results: Iterable[CertificateSpanResult],
) -> ParentCertificateStatistics:
    """Aggregate an ordered result stream without retaining all span rows."""

    counts: dict[CertificateFailureClass, int] = {}
    first_witnesses: dict[CertificateFailureClass, CertificateFailureWitness] = {}
    checked = 0
    failed = 0
    for result in results:
        expected_span = SPAN_BOUNDS[0] + checked
        if result.parent_id != parent.parent_id or result.span_ratio_ppm != expected_span:
            raise BCompletionCoordinateInvariantError(
                "certificate results are not the frozen contiguous parent traversal"
            )
        checked += 1
        if result.failures:
            failed += 1
        for witness in result.failures:
            failure_class = witness.failure_class
            counts[failure_class] = counts.get(failure_class, 0) + 1
            first_witnesses.setdefault(failure_class, witness)
    tallies = tuple(
        CertificateFailureTally(
            failure_class=failure_class,
            count=counts[failure_class],
            first_witness=first_witnesses[failure_class],
        )
        for failure_class in CERTIFICATE_FAILURE_ORDER
        if failure_class in counts
    )
    status: CertificateStatus
    if checked != CERTIFICATE_EXPECTED_SPANS_PER_PARENT:
        status = "incomplete"
    elif failed:
        status = "failed"
    else:
        status = "passed"
    return ParentCertificateStatistics(
        parent_id=parent.parent_id,
        checked_span_count=checked,
        failed_span_count=failed,
        failure_tallies=tallies,
        status=status,
    )


class SupportCertificateStatistics(BaseModel):
    """Top-level aggregate for the frozen two-parent support certificate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mapping_version: str = MAPPING_VERSION
    expected_span_count: int = CERTIFICATE_EXPECTED_SPANS
    checked_span_count: int = Field(ge=0, le=CERTIFICATE_EXPECTED_SPANS)
    failed_span_count: int = Field(ge=0)
    parents: tuple[ParentCertificateStatistics, ...]
    status: CertificateStatus

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        if self.mapping_version != MAPPING_VERSION:
            raise ValueError("certificate mapping version changed")
        if tuple(parent.parent_id for parent in self.parents) != ("p01", "p02"):
            raise ValueError("certificate parent order changed")
        checked = sum(parent.checked_span_count for parent in self.parents)
        failed = sum(parent.failed_span_count for parent in self.parents)
        if self.checked_span_count != checked or self.failed_span_count != failed:
            raise ValueError("certificate aggregate counts do not reconstruct")
        expected_status: CertificateStatus
        if checked != self.expected_span_count:
            expected_status = "incomplete"
        elif failed:
            expected_status = "failed"
        else:
            expected_status = "passed"
        if self.status != expected_status:
            raise ValueError("certificate aggregate status disagrees with its counts")
        return self


def combine_certificate_statistics(
    p01: ParentCertificateStatistics,
    p02: ParentCertificateStatistics,
) -> SupportCertificateStatistics:
    """Combine the two frozen parent aggregates into one certificate summary."""

    checked = p01.checked_span_count + p02.checked_span_count
    failed = p01.failed_span_count + p02.failed_span_count
    status: CertificateStatus
    if checked != CERTIFICATE_EXPECTED_SPANS:
        status = "incomplete"
    elif failed:
        status = "failed"
    else:
        status = "passed"
    return SupportCertificateStatistics(
        checked_span_count=checked,
        failed_span_count=failed,
        parents=(p01, p02),
        status=status,
    )
