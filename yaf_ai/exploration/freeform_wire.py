"""Preregistered Day 6 free-form wire geometry and dual-band score."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from yaf_ai.exploration.proposal_space import ProposalParameter, ProposalSpace
from yaf_core.domain.design import BoundingBox, DesignSpec
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationResult

C0 = 299_792_458.0
FREEFORM_BOX_SIZE_M = 0.040
FREEFORM_HALF_BOX_M = FREEFORM_BOX_SIZE_M / 2.0
FREEFORM_WIRE_RADIUS_M = 0.00005
FREEFORM_FEED_GAP_M = 0.0006
FREEFORM_MIN_SEGMENT_M = max(0.003, 4.0 * FREEFORM_WIRE_RADIUS_M)
FREEFORM_MIN_CLEARANCE_M = 4.0 * FREEFORM_WIRE_RADIUS_M
FREEFORM_SWEEP_HZ = (1.5e9, 6.5e9)
FREEFORM_FREQUENCY_POINTS = 251
FREEFORM_MAX_EDGE_M = C0 / FREEFORM_SWEEP_HZ[1] / 10.0
LOW_BAND_HZ = (2.40e9, 2.50e9)
HIGH_BAND_HZ = (5.725e9, 5.875e9)
FREEFORM_SPACE_BASE_VERSION = "freeform-wire-3d-v1"
DUAL_BAND_SCORE_VERSION = "dual-band-accepted-power-min-v1"
OCFD_SPACE_VERSION = "day6-ocfd-grid-v1"
DUAL_BAND_EDGE_GUARD = 3
DUAL_BAND_DEPTH_THRESHOLD_DB = -6.0
DUAL_BAND_VALIDITY_BONUS = 0.25

Point3 = tuple[float, float, float]
Segment3 = tuple[Point3, Point3]


def freeform_proposal_space(node_count: int) -> ProposalSpace:
    """Return the immutable 3N-coordinate space for one preregistered N."""

    if node_count not in {5, 6, 7}:
        raise ValueError("free-form node_count must be one of 5, 6, or 7")
    parameters = tuple(
        ProposalParameter(
            name=f"node_{index}_{axis}_m",
            lower=-FREEFORM_HALF_BOX_M,
            upper=FREEFORM_HALF_BOX_M,
        )
        for index in range(node_count)
        for axis in ("x", "y", "z")
    )
    return ProposalSpace(
        version=f"{FREEFORM_SPACE_BASE_VERSION}-n{node_count}",
        parameters=parameters,
    )


FREEFORM_PROPOSAL_SPACES: tuple[ProposalSpace, ...] = tuple(
    freeform_proposal_space(node_count) for node_count in (5, 6, 7)
)

OCFD_PROPOSAL_SPACE = ProposalSpace(
    version=OCFD_SPACE_VERSION,
    parameters=(
        ProposalParameter(name="total_length_m", lower=0.045, upper=0.069),
        ProposalParameter(name="feed_offset_ratio", lower=0.0, upper=0.35),
    ),
)


def _point(parameters: Mapping[str, float], index: int) -> Point3:
    return (
        parameters[f"node_{index}_x_m"],
        parameters[f"node_{index}_y_m"],
        parameters[f"node_{index}_z_m"],
    )


def _subtract(first: Point3, second: Point3) -> Point3:
    return (
        first[0] - second[0],
        first[1] - second[1],
        first[2] - second[2],
    )


def _add(first: Point3, second: Point3) -> Point3:
    return (
        first[0] + second[0],
        first[1] + second[1],
        first[2] + second[2],
    )


def _scale(point: Point3, factor: float) -> Point3:
    return (point[0] * factor, point[1] * factor, point[2] * factor)


def _dot(first: Point3, second: Point3) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def segment_distance(first: Segment3, second: Segment3) -> float:
    """Return the shortest Euclidean distance between two 3D segments."""

    p0, p1 = first
    q0, q1 = second
    u = _subtract(p1, p0)
    v = _subtract(q1, q0)
    w = _subtract(p0, q0)
    a = _dot(u, u)
    b = _dot(u, v)
    c = _dot(v, v)
    d = _dot(u, w)
    e = _dot(v, w)
    denominator = a * c - b * b
    epsilon = 1e-24
    s_numerator = denominator
    s_denominator = denominator
    t_numerator = denominator
    t_denominator = denominator
    if denominator < epsilon:
        s_numerator = 0.0
        s_denominator = 1.0
        t_numerator = e
        t_denominator = c
    else:
        s_numerator = b * e - c * d
        t_numerator = a * e - b * d
        if s_numerator < 0.0:
            s_numerator = 0.0
            t_numerator = e
            t_denominator = c
        elif s_numerator > s_denominator:
            s_numerator = s_denominator
            t_numerator = e + b
            t_denominator = c
    if t_numerator < 0.0:
        t_numerator = 0.0
        if -d < 0.0:
            s_numerator = 0.0
        elif -d > a:
            s_numerator = s_denominator
        else:
            s_numerator = -d
            s_denominator = a
    elif t_numerator > t_denominator:
        t_numerator = t_denominator
        if -d + b < 0.0:
            s_numerator = 0.0
        elif -d + b > a:
            s_numerator = s_denominator
        else:
            s_numerator = -d + b
            s_denominator = a
    sc = 0.0 if abs(s_numerator) < epsilon else s_numerator / s_denominator
    tc = 0.0 if abs(t_numerator) < epsilon else t_numerator / t_denominator
    separation = _subtract(_add(w, _scale(u, sc)), _scale(v, tc))
    return math.sqrt(_dot(separation, separation))


def _control_arms(parameters: Mapping[str, float], node_count: int) -> tuple[list[Point3], list[Point3]]:
    positive = [(FREEFORM_FEED_GAP_M / 2.0, 0.0, 0.0)]
    positive.extend(_point(parameters, index) for index in range(node_count))
    negative = [(-FREEFORM_FEED_GAP_M / 2.0, 0.0, 0.0)]
    negative.extend((-point[0], -point[1], -point[2]) for point in positive[1:])
    return positive, negative


def _segments(points: Sequence[Point3]) -> list[Segment3]:
    return list(zip(points, points[1:], strict=False))


def validate_control_arms(positive: Sequence[Point3], negative: Sequence[Point3]) -> None:
    """Apply the frozen physical constraints to an unsubdivided centerline."""

    if len(positive) < 2 or len(negative) != len(positive):
        raise ValueError("free-form arms must contain matching control points")
    all_points = [*positive, *negative]
    if any(
        abs(coordinate) > FREEFORM_HALF_BOX_M + 1e-12
        for point in all_points
        for coordinate in point
    ):
        raise ValueError("free-form node exceeds the 40 mm cube")
    radiating = [*_segments(positive), *_segments(negative)]
    if any(math.dist(*segment) < FREEFORM_MIN_SEGMENT_M - 1e-12 for segment in radiating):
        raise ValueError("free-form control segment is shorter than 3 mm")
    arm_length = len(positive) - 1
    indexed = [
        (arm, index, segment)
        for arm, segments in enumerate((_segments(positive), _segments(negative)))
        for index, segment in enumerate(segments)
    ]
    for left_index, (left_arm, left_position, left) in enumerate(indexed):
        for right_arm, right_position, right in indexed[left_index + 1 :]:
            adjacent = left_arm == right_arm and abs(left_position - right_position) <= 1
            feed_adjacent = (
                left_arm != right_arm
                and left_position == 0
                and right_position == 0
            )
            if adjacent or feed_adjacent:
                continue
            if segment_distance(left, right) < FREEFORM_MIN_CLEARANCE_M - 1e-12:
                raise ValueError("non-adjacent free-form segments violate 0.2 mm clearance")
    if len(radiating) != 2 * arm_length:
        raise ValueError("free-form arm indexing is inconsistent")


def _subdivide(points: Sequence[Point3]) -> list[Point3]:
    output = [points[0]]
    for start, stop in _segments(points):
        count = max(1, math.ceil(math.dist(start, stop) / FREEFORM_MAX_EDGE_M))
        for index in range(1, count + 1):
            fraction = index / count
            output.append(_add(start, _scale(_subtract(stop, start), fraction)))
    return output


def _wire_geometry(
    positive: Sequence[Point3],
    negative: Sequence[Point3],
    *,
    name: str,
    antenna_class: str,
    parameters: Mapping[str, float],
) -> Geometry:
    validate_control_arms(positive, negative)
    positive_subdivided = _subdivide(positive)
    negative_subdivided = _subdivide(negative)
    vertices: list[list[float]] = [
        list(negative_subdivided[0]),
        list(positive_subdivided[0]),
    ]
    faces: list[list[int]] = [[0, 1]]
    previous = 1
    for point in positive_subdivided[1:]:
        vertices.append(list(point))
        current = len(vertices) - 1
        faces.append([previous, current])
        previous = current
    positive_edge_count = len(positive_subdivided) - 1
    previous = 0
    for point in negative_subdivided[1:]:
        vertices.append(list(point))
        current = len(vertices) - 1
        faces.append([previous, current])
        previous = current
    total_length = FREEFORM_FEED_GAP_M + sum(
        math.dist(start, stop)
        for start, stop in [*_segments(positive), *_segments(negative)]
    )
    return Geometry(
        name=name,
        vertices=vertices,
        faces=faces,
        metadata={
            "antenna_class": antenna_class,
            "wire_radius_m": FREEFORM_WIRE_RADIUS_M,
            "box_size_m": FREEFORM_BOX_SIZE_M,
            "feed_gap_m": FREEFORM_FEED_GAP_M,
            "positive_edge_count": positive_edge_count,
            "total_wire_length_m": total_length,
            "maximum_numerical_edge_m": FREEFORM_MAX_EDGE_M,
            "control_positive": [list(point) for point in positive],
            "control_negative": [list(point) for point in negative],
            "design_features": dict(parameters),
        },
    )


def build_freeform_wire(
    parameters: Mapping[str, float], node_count: int, proposer: str
) -> Geometry:
    """Map one 3N vector to the shared native symmetric centerline."""

    space = freeform_proposal_space(node_count)
    space.validate_parameters(parameters)
    positive, negative = _control_arms(parameters, node_count)
    return _wire_geometry(
        positive,
        negative,
        name=f"{proposer}_freeform_wire_3d",
        antenna_class="freeform_wire_3d",
        parameters=parameters,
    )


def parameters_from_freeform_geometry(geometry: Geometry) -> dict[str, float]:
    """Recover the exact free-node vector recorded by the geometry generator."""

    if geometry.metadata.get("antenna_class") != "freeform_wire_3d":
        raise ValueError("geometry is not a freeform_wire_3d")
    raw = geometry.metadata.get("design_features")
    if not isinstance(raw, dict):
        raise ValueError("free-form geometry has no design_features mapping")
    return {str(name): float(value) for name, value in raw.items()}


def build_ocfd(total_length_m: float, feed_offset_ratio: float, proposer: str = "classic") -> Geometry:
    """Build the preregistered body-diagonal off-center-fed dipole."""

    parameters = {
        "total_length_m": total_length_m,
        "feed_offset_ratio": feed_offset_ratio,
    }
    OCFD_PROPOSAL_SPACE.validate_parameters(parameters)
    direction_scale = 1.0 / math.sqrt(3.0)
    direction = (direction_scale, direction_scale, direction_scale)
    low = _scale(direction, -total_length_m / 2.0)
    high = _scale(direction, total_length_m / 2.0)
    feed_center = _scale(direction, total_length_m * feed_offset_ratio)
    feed_low = _add(feed_center, _scale(direction, -FREEFORM_FEED_GAP_M / 2.0))
    feed_high = _add(feed_center, _scale(direction, FREEFORM_FEED_GAP_M / 2.0))
    positive = [feed_high, high]
    negative = [feed_low, low]
    return _wire_geometry(
        positive,
        negative,
        name=f"{proposer}_ocfd",
        antenna_class="day6_ocfd",
        parameters=parameters,
    )


def build_tuned_straight_dipole(proposer: str = "straight") -> Geometry:
    """Build the frozen 2.45 GHz center-fed body-diagonal control."""

    length = C0 / (2.0 * 2.45e9)
    geometry = build_ocfd(length, 0.0, proposer=proposer)
    return geometry.model_copy(
        update={
            "name": f"{proposer}_tuned_straight_dipole",
            "metadata": {
                **geometry.metadata,
                "antenna_class": "day6_straight_dipole",
                "reference_definition": "2.45_GHz_half_wave_body_diagonal",
            },
        }
    )


def validate_freeform_geometry(geometry: Geometry) -> None:
    """Reapply Day 6 control-line and numerical-edge invariants."""

    if geometry.metadata.get("antenna_class") not in {
        "freeform_wire_3d",
        "day6_ocfd",
        "day6_straight_dipole",
    }:
        raise ValueError("geometry is not a Day 6 native wire")
    positive_raw = geometry.metadata.get("control_positive")
    negative_raw = geometry.metadata.get("control_negative")
    if not isinstance(positive_raw, list) or not isinstance(negative_raw, list):
        raise ValueError("Day 6 wire is missing control-arm evidence")
    positive = [tuple(float(value) for value in point) for point in positive_raw]
    negative = [tuple(float(value) for value in point) for point in negative_raw]
    if any(len(point) != 3 for point in [*positive, *negative]):
        raise ValueError("Day 6 control point is not three-dimensional")
    validate_control_arms(positive, negative)  # type: ignore[arg-type]
    if any(len(face) != 2 for face in geometry.faces):
        raise ValueError("Day 6 wire may contain only two-node edges")
    for face in geometry.faces[1:]:
        if math.dist(geometry.vertices[face[0]], geometry.vertices[face[1]]) > FREEFORM_MAX_EDGE_M + 1e-12:
            raise ValueError("Day 6 numerical edge exceeds lambda(6.5 GHz)/10")


def _band_metrics(
    frequencies: Sequence[float], s11_db: Sequence[float], band: tuple[float, float]
) -> tuple[int, float, float, float]:
    indices = [
        index
        for index, frequency in enumerate(frequencies)
        if band[0] <= frequency <= band[1]
    ]
    if not indices:
        raise ValueError("dual-band score sweep does not sample a target band")
    index = min(indices, key=lambda item: s11_db[item])
    depth = s11_db[index]
    accepted_fraction = max(0.0, min(1.0, 1.0 - 10.0 ** (depth / 10.0)))
    return index, frequencies[index], depth, accepted_fraction


def _sampled_resonance_valid(index: int, s11_db: Sequence[float]) -> bool:
    """Apply the frozen internal/local/-6 dB search-shaping diagnostic."""

    return (
        DUAL_BAND_EDGE_GUARD <= index <= len(s11_db) - DUAL_BAND_EDGE_GUARD - 1
        and s11_db[index] <= DUAL_BAND_DEPTH_THRESHOLD_DB
        and s11_db[index] <= s11_db[index - 1]
        and s11_db[index] <= s11_db[index + 1]
        and (s11_db[index] < s11_db[index - 1] or s11_db[index] < s11_db[index + 1])
    )


def evaluate_dual_band_metrics(simulation: SimulationResult) -> dict[str, float]:
    """Score both bands by the frozen worst accepted-power fraction."""

    if simulation.s_params is None or not simulation.s_params.s_matrix:
        raise ValueError("dual-band scoring requires an S11 curve")
    frequencies = simulation.s_params.frequency
    s11_db = [
        20.0 * math.log10(max(abs(row[0][0]), 1e-15))
        for row in simulation.s_params.s_matrix
    ]
    low = _band_metrics(frequencies, s11_db, LOW_BAND_HZ)
    high = _band_metrics(frequencies, s11_db, HIGH_BAND_HZ)
    score = min(low[3], high[3])
    low_valid = _sampled_resonance_valid(low[0], s11_db)
    high_valid = _sampled_resonance_valid(high[0], s11_db)
    valid_both = low_valid and high_valid
    bonus = DUAL_BAND_VALIDITY_BONUS if valid_both else 0.0
    return {
        "composite_score": score,
        "band_24_index": float(low[0]),
        "band_24_frequency_hz": low[1],
        "band_24_min_s11_db": low[2],
        "band_24_mismatch_efficiency": low[3],
        "band_58_index": float(high[0]),
        "band_58_frequency_hz": high[1],
        "band_58_min_s11_db": high[2],
        "band_58_mismatch_efficiency": high[3],
        "band_24_valid_resonance": float(low_valid),
        "band_58_valid_resonance": float(high_valid),
        "valid_both_bands": float(valid_both),
        "search_validity_bonus": bonus,
        "search_score": score + bonus,
        "gain_dbi": simulation.gain_dbi or 0.0,
        "efficiency": simulation.efficiency or 0.0,
        "efficiency_weight": 0.0,
        "frequency_points": float(len(frequencies)),
        "simulation_time_seconds": simulation.simulation_time_sec,
    }


def day6_design_spec() -> DesignSpec:
    """Return the frozen wide-sweep definition used by every Day 6 run."""

    return DesignSpec(
        name="day6_freeform_dual_band",
        frequency_range=FREEFORM_SWEEP_HZ,
        target_gain_dbi=None,
        target_vswr=None,
        efficiency_target=None,
        size_constraint=BoundingBox(
            x_min=-FREEFORM_HALF_BOX_M,
            x_max=FREEFORM_HALF_BOX_M,
            y_min=-FREEFORM_HALF_BOX_M,
            y_max=FREEFORM_HALF_BOX_M,
            z_min=-FREEFORM_HALF_BOX_M,
            z_max=FREEFORM_HALF_BOX_M,
        ),
        material_palette=["copper"],
        metadata={
            "target_bands_hz": [list(LOW_BAND_HZ), list(HIGH_BAND_HZ)],
            "score_version": DUAL_BAND_SCORE_VERSION,
            "frequency_points": FREEFORM_FREQUENCY_POINTS,
        },
    )
