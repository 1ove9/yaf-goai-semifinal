"""Feasibility-preserving coordinates for the stratified paired study."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from fractions import Fraction

from yaf_ai.exploration.paired_meander import (
    MANUAL_TURN_COUNTS,
    TRAJECTORY_POINT_COUNT,
    HardwareSpec,
    PairedProposal,
    StateControl,
    audit_trajectory,
)

FEASIBLE_VECTOR_DIMENSIONS = 6
ZERO_TERMINAL_CUTOFF = Fraction(1, 16)
MAPPING_VERSION = "conditional-exact-feasible-turn-v2"

FEED_GAP_BOUNDS = (20_000, 60_000)
TERMINAL_BOUNDS = (0, 1_000_000)
STATE_A_LENGTH_BOUNDS = (50_000, 100_000)
STATE_B_LENGTH_BOUNDS = (22_000, 45_000)
SPAN_BOUNDS = (760_000, 1_000_000)

_TRAJECTORY_DENOMINATOR = TRAJECTORY_POINT_COUNT - 1
_MINIMUM_PITCH_UM = Fraction(1_500)
_MINIMUM_HEIGHT_UM = Fraction(400)
_MAXIMUM_HEIGHT_UM = Fraction(40_000)
_MINIMUM_SEGMENT_UM = Fraction(200)


class FeasibleCoordinateInvariantError(ValueError):
    """Raised when the preregistered coordinate-map invariant is violated."""


def _normalized(values: Sequence[float]) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    if len(vector) != FEASIBLE_VECTOR_DIMENSIONS:
        raise FeasibleCoordinateInvariantError(
            "feasible proposal vector must have six dimensions"
        )
    if any(not math.isfinite(value) or value < 0.0 or value > 1.0 for value in vector):
        raise FeasibleCoordinateInvariantError(
            "feasible normalized coordinates must be finite in [0,1]"
        )
    return vector


def _half_up_map(value: float, bounds: tuple[int, int]) -> int:
    lower, upper = bounds
    mapped = lower + value * (upper - lower)
    quantized = math.floor(mapped + 0.5)
    return min(upper, max(lower, quantized))


def _canonical_inverse(value: int, bounds: tuple[int, int]) -> float:
    lower, upper = bounds
    if not lower <= value <= upper:
        raise FeasibleCoordinateInvariantError("value lies outside conditional bounds")
    if lower == upper:
        return 0.5
    coordinate = float(Fraction(value - lower, upper - lower))
    if _half_up_map(coordinate, bounds) != value:
        raise FeasibleCoordinateInvariantError("canonical inverse failed to round trip")
    return coordinate


def _interpolate(start: int, end: int, index: int) -> int:
    return (
        (_TRAJECTORY_DENOMINATOR - index) * start
        + index * end
        + _TRAJECTORY_DENOMINATOR // 2
    ) // _TRAJECTORY_DENOMINATOR


def _gap_um(feed_gap_ppm: int) -> Fraction:
    return Fraction(40_000 * feed_gap_ppm, 1_000_000)


def _pitch_um(
    turn_count: int,
    feed_gap_ppm: int,
    span_ratio_ppm: int,
) -> Fraction:
    gap = _gap_um(feed_gap_ppm)
    span = Fraction(20_000 * span_ratio_ppm, 1_000_000)
    return (span - gap / 2) / (turn_count + 1)


def _height_um(
    turn_count: int,
    feed_gap_ppm: int,
    terminal_ratio_ppm: int,
    total_wire_length_um: int,
    span_ratio_ppm: int,
) -> Fraction:
    gap = _gap_um(feed_gap_ppm)
    pitch = _pitch_um(turn_count, feed_gap_ppm, span_ratio_ppm)
    terminal = Fraction(terminal_ratio_ppm, 1_000_000)
    return (
        (Fraction(total_wire_length_um) - gap) / 2
        - (turn_count + terminal) * pitch
    ) / (Fraction(turn_count) - Fraction(1, 2))


def exact_nominal_failure_reason(
    *,
    turn_count: int,
    feed_gap_ratio_ppm: int,
    terminal_ratio_ppm: int,
    state_a_length_um: int,
    state_a_span_ppm: int,
    state_b_length_um: int,
    state_b_span_ppm: int,
) -> str | None:
    """Return the first frozen exact-support failure in deterministic order."""

    terminal = Fraction(terminal_ratio_ppm, 1_000_000)
    for index in range(TRAJECTORY_POINT_COUNT):
        length_um = _interpolate(state_a_length_um, state_b_length_um, index)
        span_ppm = _interpolate(state_a_span_ppm, state_b_span_ppm, index)
        pitch = _pitch_um(turn_count, feed_gap_ratio_ppm, span_ppm)
        height = _height_um(
            turn_count,
            feed_gap_ratio_ppm,
            terminal_ratio_ppm,
            length_um,
            span_ppm,
        )
        if pitch < _MINIMUM_PITCH_UM:
            return (
                "exact_nominal_constraint_failed:pitch:"
                f"trajectory_index={index:02d}"
            )
        if height < _MINIMUM_HEIGHT_UM:
            return (
                "exact_nominal_constraint_failed:height_min:"
                f"trajectory_index={index:02d}"
            )
        if height > _MAXIMUM_HEIGHT_UM:
            return (
                "exact_nominal_constraint_failed:height_max:"
                f"trajectory_index={index:02d}"
            )
        if terminal_ratio_ppm != 0 and terminal * pitch < _MINIMUM_SEGMENT_UM:
            return (
                "exact_nominal_constraint_failed:terminal:"
                f"trajectory_index={index:02d}"
            )
    return None


def scalar_trajectory_is_legal(
    *,
    turn_count: int,
    feed_gap_ratio_ppm: int,
    terminal_ratio_ppm: int,
    state_a_length_um: int,
    state_a_span_ppm: int,
    state_b_length_um: int,
    state_b_span_ppm: int,
) -> bool:
    """Return whether all 21 points belong to the v2 exact support."""

    return exact_nominal_failure_reason(
        turn_count=turn_count,
        feed_gap_ratio_ppm=feed_gap_ratio_ppm,
        terminal_ratio_ppm=terminal_ratio_ppm,
        state_a_length_um=state_a_length_um,
        state_a_span_ppm=state_a_span_ppm,
        state_b_length_um=state_b_length_um,
        state_b_span_ppm=state_b_span_ppm,
    ) is None


def _minimum_positive_terminal(
    turn_count: int,
    feed_gap_ppm: int,
    state_a_span_ppm: int,
    state_b_span_ppm: int,
) -> int:
    minimum_pitch = min(
        _pitch_um(
            turn_count,
            feed_gap_ppm,
            _interpolate(state_a_span_ppm, state_b_span_ppm, index),
        )
        for index in range(TRAJECTORY_POINT_COUNT)
    )
    if minimum_pitch < _MINIMUM_PITCH_UM:
        raise FeasibleCoordinateInvariantError("conditional pitch is below 1.5 mm")
    threshold = _MINIMUM_SEGMENT_UM * 1_000_000 / minimum_pitch
    terminal_minimum = math.ceil(threshold)
    if terminal_minimum > TERMINAL_BOUNDS[1]:
        raise FeasibleCoordinateInvariantError("positive terminal interval is empty")
    return terminal_minimum


def _decode_terminal(value: float, terminal_minimum: int) -> int:
    cutoff = float(ZERO_TERMINAL_CUTOFF)
    if value < cutoff:
        return 0
    rescaled = (value - cutoff) / (1.0 - cutoff)
    return _half_up_map(rescaled, (terminal_minimum, TERMINAL_BOUNDS[1]))


def _encode_terminal(value: int, terminal_minimum: int) -> float:
    if value == 0:
        return float(ZERO_TERMINAL_CUTOFF / 2)
    if not terminal_minimum <= value <= TERMINAL_BOUNDS[1]:
        raise FeasibleCoordinateInvariantError("positive terminal is outside conditional bounds")
    rescaled = _canonical_inverse(value, (terminal_minimum, TERMINAL_BOUNDS[1]))
    coordinate = float(ZERO_TERMINAL_CUTOFF) + (
        1.0 - float(ZERO_TERMINAL_CUTOFF)
    ) * rescaled
    if _decode_terminal(coordinate, terminal_minimum) != value:
        raise FeasibleCoordinateInvariantError("terminal inverse failed to round trip")
    return coordinate


def _minimum_true_integer(
    lower: int,
    upper: int,
    predicate: Callable[[int], bool],
    label: str,
) -> int:
    if not predicate(upper):
        raise FeasibleCoordinateInvariantError(f"{label} conditional interval is empty")
    left = lower
    right = upper
    while left < right:
        middle = (left + right) // 2
        if predicate(middle):
            right = middle
        else:
            left = middle + 1
    return left


def _state_b_minimum(
    turn_count: int,
    feed_gap_ppm: int,
    terminal_ratio_ppm: int,
    state_a_span_ppm: int,
    state_b_span_ppm: int,
) -> int:
    return _minimum_true_integer(
        STATE_B_LENGTH_BOUNDS[0],
        STATE_B_LENGTH_BOUNDS[1],
        lambda state_b_length: scalar_trajectory_is_legal(
            turn_count=turn_count,
            feed_gap_ratio_ppm=feed_gap_ppm,
            terminal_ratio_ppm=terminal_ratio_ppm,
            state_a_length_um=STATE_A_LENGTH_BOUNDS[1],
            state_a_span_ppm=state_a_span_ppm,
            state_b_length_um=state_b_length,
            state_b_span_ppm=state_b_span_ppm,
        ),
        "state-B length",
    )


def _state_a_minimum(
    turn_count: int,
    feed_gap_ppm: int,
    terminal_ratio_ppm: int,
    state_a_span_ppm: int,
    state_b_length_um: int,
    state_b_span_ppm: int,
) -> int:
    return _minimum_true_integer(
        STATE_A_LENGTH_BOUNDS[0],
        STATE_A_LENGTH_BOUNDS[1],
        lambda state_a_length: scalar_trajectory_is_legal(
            turn_count=turn_count,
            feed_gap_ratio_ppm=feed_gap_ppm,
            terminal_ratio_ppm=terminal_ratio_ppm,
            state_a_length_um=state_a_length,
            state_a_span_ppm=state_a_span_ppm,
            state_b_length_um=state_b_length_um,
            state_b_span_ppm=state_b_span_ppm,
        ),
        "state-A length",
    )


def decode_feasible_coordinates(
    values: Sequence[float],
    *,
    turn_count: int,
    proposer: str,
) -> PairedProposal:
    """Decode one six-coordinate point without changing physical support."""

    if turn_count not in MANUAL_TURN_COUNTS:
        raise FeasibleCoordinateInvariantError("turn_count must be one of 3, 4, 5, or 6")
    vector = _normalized(values)
    feed_gap_ppm = _half_up_map(vector[0], FEED_GAP_BOUNDS)
    state_a_span_ppm = _half_up_map(vector[3], SPAN_BOUNDS)
    state_b_span_ppm = _half_up_map(vector[5], SPAN_BOUNDS)
    terminal_minimum = _minimum_positive_terminal(
        turn_count,
        feed_gap_ppm,
        state_a_span_ppm,
        state_b_span_ppm,
    )
    terminal_ratio_ppm = _decode_terminal(vector[1], terminal_minimum)
    state_b_minimum = _state_b_minimum(
        turn_count,
        feed_gap_ppm,
        terminal_ratio_ppm,
        state_a_span_ppm,
        state_b_span_ppm,
    )
    state_b_length_um = _half_up_map(
        vector[4],
        (state_b_minimum, STATE_B_LENGTH_BOUNDS[1]),
    )
    state_a_minimum = _state_a_minimum(
        turn_count,
        feed_gap_ppm,
        terminal_ratio_ppm,
        state_a_span_ppm,
        state_b_length_um,
        state_b_span_ppm,
    )
    state_a_length_um = _half_up_map(
        vector[2],
        (state_a_minimum, STATE_A_LENGTH_BOUNDS[1]),
    )
    proposal = PairedProposal(
        hardware=HardwareSpec(
            turn_count=turn_count,
            feed_gap_ratio_ppm=feed_gap_ppm,
            terminal_ratio_ppm=terminal_ratio_ppm,
        ),
        state_a=StateControl(
            state="A",
            total_wire_length_um=state_a_length_um,
            span_ratio_ppm=state_a_span_ppm,
        ),
        state_b=StateControl(
            state="B",
            total_wire_length_um=state_b_length_um,
            span_ratio_ppm=state_b_span_ppm,
        ),
        proposer=proposer,
    )
    failure_reason = exact_nominal_failure_reason(
        turn_count=turn_count,
        feed_gap_ratio_ppm=feed_gap_ppm,
        terminal_ratio_ppm=terminal_ratio_ppm,
        state_a_length_um=state_a_length_um,
        state_a_span_ppm=state_a_span_ppm,
        state_b_length_um=state_b_length_um,
        state_b_span_ppm=state_b_span_ppm,
    )
    if failure_reason is not None:
        raise FeasibleCoordinateInvariantError(failure_reason)
    audit = audit_trajectory(proposal)
    if not audit.valid:
        raise FeasibleCoordinateInvariantError(
            f"decoded proposal failed the frozen trajectory audit: {audit.rejection_reason}"
        )
    return proposal


def decode_feasible_normalized(
    turn_count: int,
    values: Sequence[float],
    proposer: str,
) -> PairedProposal:
    """Compatibility wrapper with the stratified-agent argument order."""

    return decode_feasible_coordinates(
        values,
        turn_count=turn_count,
        proposer=proposer,
    )


def encode_feasible_coordinates(proposal: PairedProposal) -> tuple[float, ...]:
    """Return the canonical six-coordinate preimage of a legal proposal."""

    audit = audit_trajectory(proposal)
    if not audit.valid:
        raise FeasibleCoordinateInvariantError(
            f"cannot encode an illegal proposal: {audit.rejection_reason}"
        )
    hardware = proposal.hardware
    failure_reason = exact_nominal_failure_reason(
        turn_count=hardware.turn_count,
        feed_gap_ratio_ppm=hardware.feed_gap_ratio_ppm,
        terminal_ratio_ppm=hardware.terminal_ratio_ppm,
        state_a_length_um=proposal.state_a.total_wire_length_um,
        state_a_span_ppm=proposal.state_a.span_ratio_ppm,
        state_b_length_um=proposal.state_b.total_wire_length_um,
        state_b_span_ppm=proposal.state_b.span_ratio_ppm,
    )
    if failure_reason is not None:
        raise FeasibleCoordinateInvariantError(failure_reason)
    terminal_minimum = _minimum_positive_terminal(
        hardware.turn_count,
        hardware.feed_gap_ratio_ppm,
        proposal.state_a.span_ratio_ppm,
        proposal.state_b.span_ratio_ppm,
    )
    state_b_minimum = _state_b_minimum(
        hardware.turn_count,
        hardware.feed_gap_ratio_ppm,
        hardware.terminal_ratio_ppm,
        proposal.state_a.span_ratio_ppm,
        proposal.state_b.span_ratio_ppm,
    )
    state_a_minimum = _state_a_minimum(
        hardware.turn_count,
        hardware.feed_gap_ratio_ppm,
        hardware.terminal_ratio_ppm,
        proposal.state_a.span_ratio_ppm,
        proposal.state_b.total_wire_length_um,
        proposal.state_b.span_ratio_ppm,
    )
    vector = (
        _canonical_inverse(hardware.feed_gap_ratio_ppm, FEED_GAP_BOUNDS),
        _encode_terminal(hardware.terminal_ratio_ppm, terminal_minimum),
        _canonical_inverse(
            proposal.state_a.total_wire_length_um,
            (state_a_minimum, STATE_A_LENGTH_BOUNDS[1]),
        ),
        _canonical_inverse(proposal.state_a.span_ratio_ppm, SPAN_BOUNDS),
        _canonical_inverse(
            proposal.state_b.total_wire_length_um,
            (state_b_minimum, STATE_B_LENGTH_BOUNDS[1]),
        ),
        _canonical_inverse(proposal.state_b.span_ratio_ppm, SPAN_BOUNDS),
    )
    decoded = decode_feasible_coordinates(
        vector,
        turn_count=hardware.turn_count,
        proposer=proposal.proposer,
    )
    if decoded != proposal:
        raise FeasibleCoordinateInvariantError("canonical proposal round trip changed bytes")
    return vector
