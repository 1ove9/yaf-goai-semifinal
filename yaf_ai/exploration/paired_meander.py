"""Frozen paired-state meander definitions for the GOAI semifinal study."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_core.domain.geometry import Geometry

MECHANISM_VERSION = "ideal-symmetric-telescopic-PEC-meander-v1"
QUANTIZATION_VERSION = "integer-um-ppm-v1"
PAIR_SCHEMA_VERSION = 1

BOX_SIZE_UM = 40_000
HALF_BOX_M = 0.020
WIRE_RADIUS_UM = 50
WIRE_RADIUS_M = 0.00005
MAX_TOTAL_WIRE_LENGTH_UM = 100_000
MINIMUM_PITCH_M = 0.0015
MINIMUM_SEGMENT_M = 4.0 * WIRE_RADIUS_M
TRAJECTORY_POINT_COUNT = 21
MAX_CONSECUTIVE_REJECTIONS = 100
MAX_TOTAL_PROPOSAL_ATTEMPTS = 6000

STATE_A_FREQUENCIES_HZ = tuple(2.400e9 + index * (2.500e9 - 2.400e9) / 100 for index in range(101))
STATE_B_FREQUENCIES_HZ = tuple(5.725e9 + index * (5.875e9 - 5.725e9) / 100 for index in range(101))

MANUAL_TURN_COUNTS = (3, 4, 5, 6)
MANUAL_FEED_GAP_RATIO_PPM = (20_000, 40_000, 60_000)
MANUAL_TERMINAL_RATIO_PPM = (0, 500_000, 1_000_000)
MANUAL_A_LENGTH_UM = (52_005, 61_182, 70_359, 79_537)
MANUAL_B_LENGTH_UM = (22_000, 25_844, 29_721, 33_597)
MANUAL_SPAN_RATIO_PPM = (760_000, 880_000, 1_000_000)

StateLabel = Literal["A", "B"]


class PairedMeanderError(ValueError):
    """Base error for a preregistered paired-state contract violation."""


class PairedProposalRejected(PairedMeanderError):  # noqa: N818
    """Raised before a solver call when geometry or trajectory is illegal."""


class AnchorNotReleasedError(PairedMeanderError):
    """Raised when the high-frequency renderer gate is not released."""


class PairBudgetExhaustedError(PairedMeanderError):
    """Raised after the accepted paired-evaluation budget is consumed."""


class HardwareSpec(BaseModel):
    """Quantized hardware identity shared byte-for-byte by both states."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = PAIR_SCHEMA_VERSION
    mechanism_version: str = MECHANISM_VERSION
    quantization_version: str = QUANTIZATION_VERSION
    turn_count: int = Field(ge=3, le=6)
    feed_gap_ratio_ppm: int = Field(ge=20_000, le=60_000)
    terminal_ratio_ppm: int = Field(ge=0, le=1_000_000)
    max_total_wire_length_um: int = MAX_TOTAL_WIRE_LENGTH_UM
    box_size_um: int = BOX_SIZE_UM
    wire_radius_um: int = WIRE_RADIUS_UM

    @model_validator(mode="after")
    def validate_frozen_constants(self) -> Self:
        """Reject values outside the frozen mechanism and quantization."""

        if self.turn_count not in MANUAL_TURN_COUNTS:
            raise ValueError("turn_count must be one of 3, 4, 5, or 6")
        if self.mechanism_version != MECHANISM_VERSION:
            raise ValueError("mechanism_version is frozen")
        if self.quantization_version != QUANTIZATION_VERSION:
            raise ValueError("quantization_version is frozen")
        if self.max_total_wire_length_um != MAX_TOTAL_WIRE_LENGTH_UM:
            raise ValueError("max_total_wire_length_um is frozen")
        if self.box_size_um != BOX_SIZE_UM:
            raise ValueError("box_size_um is frozen")
        if self.wire_radius_um != WIRE_RADIUS_UM:
            raise ValueError("wire_radius_um is frozen")
        return self


class StateControl(BaseModel):
    """One quantized actuator setting under its state-specific bounds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: StateLabel
    total_wire_length_um: int
    span_ratio_ppm: int = Field(ge=760_000, le=1_000_000)

    @model_validator(mode="after")
    def validate_state_bounds(self) -> Self:
        """Apply the preregistered disjoint length ranges."""

        lower, upper = (50_000, 100_000) if self.state == "A" else (22_000, 45_000)
        if not lower <= self.total_wire_length_um <= upper:
            raise ValueError(
                f"state {self.state} total_wire_length_um must be in [{lower}, {upper}]"
            )
        return self


class PairedProposal(BaseModel):
    """A single hardware object and its two immutable state controls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hardware: HardwareSpec
    state_a: StateControl
    state_b: StateControl
    proposer: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_state_labels(self) -> Self:
        """Prevent accidentally swapping or duplicating the state roles."""

        if self.state_a.state != "A" or self.state_b.state != "B":
            raise ValueError("paired proposal requires state_a=A and state_b=B")
        return self


class SearchCurve(BaseModel):
    """One source-addressable target-band curve used by the search scorer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    solver_name: str
    solver_mode: str
    frequency_hz: tuple[float, ...]
    s11_db: tuple[float, ...]
    realized_gain_dbi: tuple[float, ...] | None = None

    @model_validator(mode="after")
    def validate_lengths(self) -> Self:
        """Require one S11 value, and optionally one gain value, per bin."""

        if len(self.frequency_hz) != len(self.s11_db):
            raise ValueError("frequency_hz and s11_db lengths differ")
        if self.realized_gain_dbi is not None and len(self.realized_gain_dbi) != len(
            self.frequency_hz
        ):
            raise ValueError("realized_gain_dbi length differs from frequency_hz")
        if not self.frequency_hz:
            raise ValueError("search curve is empty")
        return self


class StateSearchMetrics(BaseModel):
    """Frozen selected-bin metrics for one state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: StateLabel
    selected_index: int = Field(ge=0, le=100)
    selected_frequency_hz: float
    selected_s11_db: float
    valid_search: bool
    figure_of_merit: float
    reflected_power_fraction: float
    realized_gain_dbi: float | None


class PairedMetrics(BaseModel):
    """The only paired search score admitted by the semifinal study."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state_a: StateSearchMetrics
    state_b: StateSearchMetrics
    base_score: float
    valid_pair_search: bool
    search_score: float
    worst_reflected_power_fraction: float


class TrajectoryAudit(BaseModel):
    """A disclosed 21-point discrete path audit, not a continuity proof."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    point_count: int = TRAJECTORY_POINT_COUNT
    valid: bool
    minimum_clearance_m: float | None
    minimum_pitch_m: float | None
    minimum_height_m: float | None
    maximum_adjacent_node_displacement_m: float | None
    state_geometry_hashes: tuple[str, ...]
    rejection_reason: str | None = None


class PairedEvaluation(BaseModel):
    """One accepted pair evaluated with exactly two NEC2 target-band curves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hardware_hash: str
    state_a_geometry_hash: str
    state_b_geometry_hash: str
    pair_hash: str
    metrics: PairedMetrics
    trajectory: TrajectoryAudit
    state_a_curve: SearchCurve
    state_b_curve: SearchCurve


class ManualGridWitness(BaseModel):
    """The first deterministic legal pair in the frozen manual grid."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hardware_grid_index: int = Field(ge=0)
    pair_grid_index: int = Field(ge=0)
    proposal: PairedProposal
    trajectory: TrajectoryAudit


PairedSolver = Callable[[Geometry, StateLabel, tuple[float, ...]], Awaitable[SearchCurve]]


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def quantize_length_m_to_um(value_m: float) -> int:
    """Quantize metres to integer micrometres using decimal half-up."""

    if not math.isfinite(value_m):
        raise PairedMeanderError("length must be finite")
    return int(
        (Decimal(str(value_m)) * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def quantize_ratio_to_ppm(value: float) -> int:
    """Quantize a dimensionless ratio to integer ppm using decimal half-up."""

    if not math.isfinite(value):
        raise PairedMeanderError("ratio must be finite")
    return int(
        (Decimal(str(value)) * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def hardware_hash(hardware: HardwareSpec) -> str:
    """Hash only the frozen, quantized shared hardware identity."""

    return _sha256(hardware.model_dump(mode="json"))


def require_same_hardware(
    first: HardwareSpec,
    second: HardwareSpec,
) -> str:
    """Reject a shared-field mismatch before either state reaches a solver."""

    first_hash = hardware_hash(first)
    if first_hash != hardware_hash(second):
        raise PairedProposalRejected("state hardware identities differ")
    return first_hash


def _geometry_payload(
    hardware: HardwareSpec,
    state: StateControl,
    geometry: Geometry,
) -> dict[str, object]:
    return {
        "schema_version": PAIR_SCHEMA_VERSION,
        "mechanism_version": MECHANISM_VERSION,
        "quantization_version": QUANTIZATION_VERSION,
        "hardware": hardware.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "vertices": geometry.vertices,
        "faces": geometry.faces,
    }


def state_geometry_hash(
    hardware: HardwareSpec,
    state: StateControl,
    geometry: Geometry | None = None,
) -> str:
    """Hash a state geometry reconstructed from the same quantized objects."""

    built = geometry if geometry is not None else build_state_geometry(hardware, state)
    return _sha256(_geometry_payload(hardware, state, built))


def pair_hash(proposal: PairedProposal) -> str:
    """Hash the shared hardware and both state geometry identities."""

    geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
    geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
    return _sha256(
        {
            "schema_version": PAIR_SCHEMA_VERSION,
            "hardware_hash": hardware_hash(proposal.hardware),
            "state_a_geometry_hash": state_geometry_hash(
                proposal.hardware, proposal.state_a, geometry_a
            ),
            "state_b_geometry_hash": state_geometry_hash(
                proposal.hardware, proposal.state_b, geometry_b
            ),
        }
    )


def _geometry_values(
    hardware: HardwareSpec,
    total_wire_length_um: int,
    span_ratio_ppm: int,
) -> tuple[float, float, float, float]:
    gap = hardware.box_size_um * 1e-6 * hardware.feed_gap_ratio_ppm / 1_000_000
    span = hardware.box_size_um * 1e-6 / 2.0 * span_ratio_ppm / 1_000_000
    pitch = (span - gap / 2.0) / (hardware.turn_count + 1)
    terminal_ratio = hardware.terminal_ratio_ppm / 1_000_000
    horizontal = (hardware.turn_count + terminal_ratio) * pitch
    total_length_m = total_wire_length_um * 1e-6
    height = ((total_length_m - gap) / 2.0 - horizontal) / (hardware.turn_count - 0.5)
    return gap, span, pitch, height


def _build_quantized_geometry(
    hardware: HardwareSpec,
    total_wire_length_um: int,
    span_ratio_ppm: int,
    label: str,
) -> Geometry:
    gap, _span, pitch, height = _geometry_values(hardware, total_wire_length_um, span_ratio_ppm)
    terminal_ratio = hardware.terminal_ratio_ppm / 1_000_000
    right: list[tuple[float, float, float]] = [(gap / 2.0, 0.0, 0.0)]
    y = height / 2.0
    right.append((gap / 2.0, y, 0.0))
    x = gap / 2.0
    for index in range(hardware.turn_count):
        x += pitch
        right.append((x, y, 0.0))
        if index < hardware.turn_count - 1:
            y = -y
            right.append((x, y, 0.0))
    terminal_increment = terminal_ratio * pitch
    if terminal_increment > 0.0:
        x += terminal_increment
        right.append((x, y, 0.0))

    vertices: list[list[float]] = [
        [-gap / 2.0, 0.0, 0.0],
        [gap / 2.0, 0.0, 0.0],
    ]
    faces: list[list[int]] = [[0, 1]]
    previous = 1
    for point in right[1:]:
        vertices.append(list(point))
        current = len(vertices) - 1
        faces.append([previous, current])
        previous = current
    previous = 0
    for point in right[1:]:
        vertices.append([-point[0], -point[1], -point[2]])
        current = len(vertices) - 1
        faces.append([previous, current])
        previous = current

    geometry = Geometry(
        name=f"{label}_paired_meander",
        vertices=vertices,
        faces=faces,
        metadata={
            "antenna_class": "meander_dipole",
            "mechanism_version": MECHANISM_VERSION,
            "quantization_version": QUANTIZATION_VERSION,
            "wire_radius_m": hardware.wire_radius_um * 1e-6,
            "box_size_m": hardware.box_size_um * 1e-6,
            "feed_gap_m": gap,
            "turn_count": hardware.turn_count,
            "minimum_pitch_m": pitch,
            "derived_height_m": height,
            "total_wire_length_m": sum(
                math.dist(vertices[edge[0]], vertices[edge[1]]) for edge in faces
            ),
            "target_total_wire_length_m": total_wire_length_um * 1e-6,
            "design_features": {
                "turn_count": hardware.turn_count,
                "feed_gap_ratio_ppm": hardware.feed_gap_ratio_ppm,
                "terminal_ratio_ppm": hardware.terminal_ratio_ppm,
                "total_wire_length_um": total_wire_length_um,
                "span_ratio_ppm": span_ratio_ppm,
            },
        },
    )
    validate_paired_geometry(geometry)
    return geometry


def build_state_geometry(
    hardware: HardwareSpec,
    state: StateControl,
) -> Geometry:
    """Build one endpoint with the sole preregistered centerline equation."""

    return _build_quantized_geometry(
        hardware,
        state.total_wire_length_um,
        state.span_ratio_ppm,
        state.state,
    )


def _orientation(
    first: Sequence[float],
    second: Sequence[float],
    third: Sequence[float],
) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (
        third[0] - first[0]
    )


def _on_segment(
    first: Sequence[float],
    second: Sequence[float],
    point: Sequence[float],
) -> bool:
    tolerance = 1e-12
    return (
        min(first[0], second[0]) - tolerance <= point[0] <= max(first[0], second[0]) + tolerance
        and min(first[1], second[1]) - tolerance <= point[1] <= max(first[1], second[1]) + tolerance
    )


def _segments_intersect(
    first_a: Sequence[float],
    first_b: Sequence[float],
    second_a: Sequence[float],
    second_b: Sequence[float],
) -> bool:
    tolerance = 1e-12
    o1 = _orientation(first_a, first_b, second_a)
    o2 = _orientation(first_a, first_b, second_b)
    o3 = _orientation(second_a, second_b, first_a)
    o4 = _orientation(second_a, second_b, first_b)
    if o1 * o2 < -tolerance and o3 * o4 < -tolerance:
        return True
    checks = (
        (abs(o1) <= tolerance and _on_segment(first_a, first_b, second_a)),
        (abs(o2) <= tolerance and _on_segment(first_a, first_b, second_b)),
        (abs(o3) <= tolerance and _on_segment(second_a, second_b, first_a)),
        (abs(o4) <= tolerance and _on_segment(second_a, second_b, first_b)),
    )
    return any(checks)


def _point_segment_distance(
    point: Sequence[float],
    start: Sequence[float],
    end: Sequence[float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.dist(point[:2], start[:2])
    fraction = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    fraction = min(1.0, max(0.0, fraction))
    closest = (start[0] + fraction * dx, start[1] + fraction * dy)
    return math.dist(point[:2], closest)


def _segment_distance(
    first_a: Sequence[float],
    first_b: Sequence[float],
    second_a: Sequence[float],
    second_b: Sequence[float],
) -> float:
    if _segments_intersect(first_a, first_b, second_a, second_b):
        return 0.0
    return min(
        _point_segment_distance(first_a, second_a, second_b),
        _point_segment_distance(first_b, second_a, second_b),
        _point_segment_distance(second_a, first_a, first_b),
        _point_segment_distance(second_b, first_a, first_b),
    )


def minimum_nonadjacent_clearance(geometry: Geometry) -> float:
    """Return centerline clearance between every pair of nonadjacent edges."""

    minimum = math.inf
    for first_index, first_edge in enumerate(geometry.faces):
        first_nodes = set(first_edge)
        for second_edge in geometry.faces[first_index + 1 :]:
            if first_nodes.intersection(second_edge):
                continue
            distance = _segment_distance(
                geometry.vertices[first_edge[0]],
                geometry.vertices[first_edge[1]],
                geometry.vertices[second_edge[0]],
                geometry.vertices[second_edge[1]],
            )
            minimum = min(minimum, distance)
    return minimum


def validate_paired_geometry(geometry: Geometry) -> None:
    """Reject any deviation from the frozen 40 mm meander geometry contract."""

    if geometry.metadata.get("antenna_class") != "meander_dipole":
        raise PairedProposalRejected("paired geometry must use the meander path")
    if geometry.metadata.get("mechanism_version") != MECHANISM_VERSION:
        raise PairedProposalRejected("paired mechanism version changed")
    if not geometry.vertices or not geometry.faces:
        raise PairedProposalRejected("paired geometry is empty")
    if geometry.faces[0] != [0, 1]:
        raise PairedProposalRejected("the first edge must be the feed edge")
    gap = float(geometry.metadata.get("feed_gap_m", 0.0))
    expected_feed = (
        [-gap / 2.0, 0.0, 0.0],
        [gap / 2.0, 0.0, 0.0],
    )
    if geometry.vertices[0] != expected_feed[0] or geometry.vertices[1] != expected_feed[1]:
        raise PairedProposalRejected("feed edge vertices changed")

    adjacency: dict[int, set[int]] = {index: set() for index in range(len(geometry.vertices))}
    total_length = 0.0
    for edge in geometry.faces:
        if len(edge) != 2 or any(node < 0 or node >= len(geometry.vertices) for node in edge):
            raise PairedProposalRejected("paired geometry contains an invalid edge")
        start, end = edge
        adjacency[start].add(end)
        adjacency[end].add(start)
        length = math.dist(geometry.vertices[start], geometry.vertices[end])
        if length < MINIMUM_SEGMENT_M - 1e-12:
            raise PairedProposalRejected("paired geometry contains a short segment")
        total_length += length

    visited = {0}
    frontier = [0]
    while frontier:
        node = frontier.pop()
        for neighbour in adjacency[node]:
            if neighbour not in visited:
                visited.add(neighbour)
                frontier.append(neighbour)
    if len(visited) != len(geometry.vertices):
        raise PairedProposalRejected("paired geometry is disconnected")

    for vertex in geometry.vertices:
        if (
            abs(vertex[0]) > HALF_BOX_M + 1e-12
            or abs(vertex[1]) > HALF_BOX_M + 1e-12
            or abs(vertex[2]) > 1e-12
        ):
            raise PairedProposalRejected("paired geometry exceeds the 40 mm box")

    pitch = float(geometry.metadata.get("minimum_pitch_m", 0.0))
    height = float(geometry.metadata.get("derived_height_m", 0.0))
    if height <= 0.0:
        raise PairedProposalRejected("derived height is not positive")
    if height / 2.0 > HALF_BOX_M + 1e-12:
        raise PairedProposalRejected("derived height exceeds the 40 mm box")
    if pitch < MINIMUM_PITCH_M - 1e-12:
        raise PairedProposalRejected("pitch is below 1.5 mm")

    target = float(geometry.metadata.get("target_total_wire_length_m", 0.0))
    if abs(total_length - target) > 1e-9:
        raise PairedProposalRejected("geometry does not realize requested wire length")
    clearance = minimum_nonadjacent_clearance(geometry)
    if clearance < MINIMUM_SEGMENT_M - 1e-12:
        raise PairedProposalRejected("paired geometry self-intersects or collides")


def _interpolate_integer(start: int, end: int, index: int) -> int:
    numerator = (TRAJECTORY_POINT_COUNT - 1 - index) * start + index * end
    denominator = TRAJECTORY_POINT_COUNT - 1
    return (numerator + denominator // 2) // denominator


def audit_trajectory(proposal: PairedProposal) -> TrajectoryAudit:
    """Audit 21 linearly interpolated actuator settings with one generator."""

    geometries: list[Geometry] = []
    hashes: list[str] = []
    minimum_clearance = math.inf
    minimum_pitch = math.inf
    minimum_height = math.inf
    maximum_displacement = 0.0
    previous: Geometry | None = None
    try:
        for index in range(TRAJECTORY_POINT_COUNT):
            length_um = _interpolate_integer(
                proposal.state_a.total_wire_length_um,
                proposal.state_b.total_wire_length_um,
                index,
            )
            span_ppm = _interpolate_integer(
                proposal.state_a.span_ratio_ppm,
                proposal.state_b.span_ratio_ppm,
                index,
            )
            geometry = _build_quantized_geometry(
                proposal.hardware,
                length_um,
                span_ppm,
                f"trajectory_{index:02d}",
            )
            geometries.append(geometry)
            minimum_clearance = min(
                minimum_clearance,
                minimum_nonadjacent_clearance(geometry),
            )
            minimum_pitch = min(
                minimum_pitch,
                float(geometry.metadata["minimum_pitch_m"]),
            )
            minimum_height = min(
                minimum_height,
                float(geometry.metadata["derived_height_m"]),
            )
            hashes.append(
                _sha256(
                    {
                        "hardware_hash": hardware_hash(proposal.hardware),
                        "trajectory_index": index,
                        "length_um": length_um,
                        "span_ratio_ppm": span_ppm,
                        "vertices": geometry.vertices,
                        "faces": geometry.faces,
                    }
                )
            )
            if previous is not None:
                if len(previous.vertices) != len(geometry.vertices):
                    raise PairedProposalRejected(
                        "trajectory topology changes between adjacent states"
                    )
                maximum_displacement = max(
                    maximum_displacement,
                    max(
                        math.dist(left, right)
                        for left, right in zip(
                            previous.vertices,
                            geometry.vertices,
                            strict=True,
                        )
                    ),
                )
            previous = geometry
    except PairedMeanderError as error:
        return TrajectoryAudit(
            valid=False,
            minimum_clearance_m=(None if minimum_clearance == math.inf else minimum_clearance),
            minimum_pitch_m=None if minimum_pitch == math.inf else minimum_pitch,
            minimum_height_m=None if minimum_height == math.inf else minimum_height,
            maximum_adjacent_node_displacement_m=(None if not geometries else maximum_displacement),
            state_geometry_hashes=tuple(hashes),
            rejection_reason=str(error),
        )
    return TrajectoryAudit(
        valid=True,
        minimum_clearance_m=minimum_clearance,
        minimum_pitch_m=minimum_pitch,
        minimum_height_m=minimum_height,
        maximum_adjacent_node_displacement_m=maximum_displacement,
        state_geometry_hashes=tuple(hashes),
    )


def _expected_frequency_table(state: StateLabel) -> tuple[float, ...]:
    return STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ


def score_state_curve(
    curve: SearchCurve,
    state: StateLabel,
) -> StateSearchMetrics:
    """Select the global minimum and apply the frozen NEC2-only validity gate."""

    expected = _expected_frequency_table(state)
    if curve.solver_name.lower() != "nec2":
        raise PairedMeanderError("paired search scoring accepts NEC2 only")
    if curve.solver_mode not in {"native", "subprocess"}:
        raise PairedMeanderError("paired search scoring requires a real solver mode")
    if curve.frequency_hz != expected:
        raise PairedMeanderError(f"state {state} frequency table changed")
    selected_index = min(
        range(len(curve.s11_db)),
        key=lambda index: (curve.s11_db[index], index),
    )
    selected_s11 = curve.s11_db[selected_index]
    reflected = math.pow(10.0, selected_s11 / 10.0)
    gain = None if curve.realized_gain_dbi is None else curve.realized_gain_dbi[selected_index]
    return StateSearchMetrics(
        state=state,
        selected_index=selected_index,
        selected_frequency_hz=curve.frequency_hz[selected_index],
        selected_s11_db=selected_s11,
        valid_search=3 <= selected_index <= 97 and selected_s11 <= -6.0,
        figure_of_merit=1.0 - reflected,
        reflected_power_fraction=reflected,
        realized_gain_dbi=gain,
    )


def score_paired_curves(
    state_a_curve: SearchCurve,
    state_b_curve: SearchCurve,
) -> PairedMetrics:
    """Compute the sole frozen paired base score and shaped search score."""

    state_a = score_state_curve(state_a_curve, "A")
    state_b = score_state_curve(state_b_curve, "B")
    valid_pair = state_a.valid_search and state_b.valid_search
    base_score = min(state_a.figure_of_merit, state_b.figure_of_merit)
    return PairedMetrics(
        state_a=state_a,
        state_b=state_b,
        base_score=base_score,
        valid_pair_search=valid_pair,
        search_score=base_score + (0.25 if valid_pair else 0.0),
        worst_reflected_power_fraction=max(
            state_a.reflected_power_fraction,
            state_b.reflected_power_fraction,
        ),
    )


class PairedStateEnvironment:
    """Small injected-solver environment used before the production runner."""

    def __init__(
        self,
        *,
        solver: PairedSolver,
        evaluation_budget: int,
        anchor_released: bool,
    ) -> None:
        if evaluation_budget <= 0:
            raise ValueError("evaluation_budget must be positive")
        self._solver = solver
        self._evaluation_budget = evaluation_budget
        self._anchor_released = anchor_released
        self._evaluations_completed = 0
        self._rejections = 0

    @property
    def evaluations_completed(self) -> int:
        return self._evaluations_completed

    @property
    def rejections(self) -> int:
        return self._rejections

    async def evaluate(self, proposal: PairedProposal) -> PairedEvaluation:
        """Run exactly the two target bands after all geometry-only gates pass."""

        if self._evaluations_completed >= self._evaluation_budget:
            raise PairBudgetExhaustedError("paired evaluation budget exhausted")
        trajectory = audit_trajectory(proposal)
        if not trajectory.valid:
            self._rejections += 1
            raise PairedProposalRejected(trajectory.rejection_reason or "trajectory audit failed")
        geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
        geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
        curve_a = await self._solver(
            geometry_a,
            "A",
            STATE_A_FREQUENCIES_HZ,
        )
        curve_b = await self._solver(
            geometry_b,
            "B",
            STATE_B_FREQUENCIES_HZ,
        )
        metrics = score_paired_curves(curve_a, curve_b)
        self._evaluations_completed += 1
        return PairedEvaluation(
            hardware_hash=hardware_hash(proposal.hardware),
            state_a_geometry_hash=state_geometry_hash(
                proposal.hardware, proposal.state_a, geometry_a
            ),
            state_b_geometry_hash=state_geometry_hash(
                proposal.hardware, proposal.state_b, geometry_b
            ),
            pair_hash=pair_hash(proposal),
            metrics=metrics,
            trajectory=trajectory,
            state_a_curve=curve_a,
            state_b_curve=curve_b,
        )


def manual_hardware_grid() -> tuple[HardwareSpec, ...]:
    """Return all 36 shared hardware rows in frozen field order."""

    return tuple(
        HardwareSpec(
            turn_count=turn_count,
            feed_gap_ratio_ppm=feed_gap,
            terminal_ratio_ppm=terminal,
        )
        for turn_count in MANUAL_TURN_COUNTS
        for feed_gap in MANUAL_FEED_GAP_RATIO_PPM
        for terminal in MANUAL_TERMINAL_RATIO_PPM
    )


def manual_state_grid(state: StateLabel) -> tuple[StateControl, ...]:
    """Return the 12 fixed integer state rows for A or B."""

    lengths = MANUAL_A_LENGTH_UM if state == "A" else MANUAL_B_LENGTH_UM
    return tuple(
        StateControl(
            state=state,
            total_wire_length_um=length,
            span_ratio_ppm=span,
        )
        for length in lengths
        for span in MANUAL_SPAN_RATIO_PPM
    )


def iter_manual_pairs() -> Iterator[tuple[int, int, PairedProposal]]:
    """Yield the 5,184 geometric pair combinations in frozen sort order."""

    pair_index = 0
    state_a = manual_state_grid("A")
    state_b = manual_state_grid("B")
    for hardware_index, hardware in enumerate(manual_hardware_grid()):
        for first in state_a:
            for second in state_b:
                yield (
                    hardware_index,
                    pair_index,
                    PairedProposal(
                        hardware=hardware,
                        state_a=first,
                        state_b=second,
                        proposer="manual-physics-baseline",
                    ),
                )
                pair_index += 1


def manual_grid_single_state_evaluations() -> int:
    """Return the preregistered cached single-state solve count."""

    return len(manual_hardware_grid()) * (len(manual_state_grid("A")) + len(manual_state_grid("B")))


def find_manual_geometric_witness() -> ManualGridWitness:
    """Return the first legal endpoint pair and 21-point trajectory."""

    for hardware_index, pair_index, proposal in iter_manual_pairs():
        trajectory = audit_trajectory(proposal)
        if trajectory.valid:
            return ManualGridWitness(
                hardware_grid_index=hardware_index,
                pair_grid_index=pair_index,
                proposal=proposal,
                trajectory=trajectory,
            )
    raise PairedMeanderError("the frozen manual grid has no legal pair")


def select_timing_preflight_pairs(
    proposals: Iterable[PairedProposal],
) -> tuple[PairedProposal, ...]:
    """Select the frozen hash-ordered timing-only set without solver results."""

    legal: list[tuple[str, PairedProposal]] = []
    for proposal in proposals:
        if audit_trajectory(proposal).valid:
            digest = hashlib.sha256(
                ("yaf-semifinal-v3.4-preflight|" + pair_hash(proposal)).encode("utf-8")
            ).hexdigest()
            legal.append((digest, proposal))
    legal.sort(key=lambda item: item[0])
    if len(legal) < 20:
        raise PairedMeanderError("fewer than 20 legal timing-preflight pairs")
    return tuple(proposal for _digest, proposal in legal[:20])
