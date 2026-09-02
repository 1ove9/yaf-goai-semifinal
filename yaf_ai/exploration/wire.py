"""Shared native centerline geometry for constrained meander-dipole exploration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from yaf_core.domain.design import BoundingBox, DesignSpec
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationResult

WIRE_BOX_SIZE_M = 0.030
WIRE_HALF_BOX_M = WIRE_BOX_SIZE_M / 2.0
WIRE_RADIUS_M = 0.00005
MINIMUM_PITCH_M = 0.0015
MAXIMUM_TOTAL_WIRE_LENGTH_M = 0.25
WIRE_GAIN_TARGET_DBI = 2.15
MINIMUM_MISMATCH_EFFICIENCY = 1e-300


def build_meander_dipole(
    parameters: Mapping[str, float], proposer: str
) -> Geometry:
    """Build a symmetric planar meander from one registered five-D space."""

    turns = int(round(parameters["turns"]))
    span = WIRE_HALF_BOX_M * parameters["span_ratio"]
    gap = WIRE_BOX_SIZE_M * parameters["feed_gap_ratio"]
    terminal_ratio = parameters["terminal_ratio"]
    available_span = span - gap / 2.0
    pitch = available_span / (turns + 1)
    if "total_length_m" in parameters:
        horizontal_arm_length = (turns + terminal_ratio) * pitch
        vertical_transitions = turns - 0.5
        height = (
            (parameters["total_length_m"] - gap) / 2.0
            - horizontal_arm_length
        ) / vertical_transitions
    else:
        height = WIRE_BOX_SIZE_M * parameters["height_ratio"]

    right: list[tuple[float, float, float]] = [(gap / 2.0, 0.0, 0.0)]
    y = height / 2.0
    right.append((gap / 2.0, y, 0.0))
    x = gap / 2.0
    for index in range(turns):
        x += pitch
        right.append((x, y, 0.0))
        if index < turns - 1:
            y = -y
            right.append((x, y, 0.0))
    x += terminal_ratio * pitch
    if x > right[-1][0] + 1e-12:
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
        mirrored = [-point[0], -point[1], -point[2]]
        vertices.append(mirrored)
        current = len(vertices) - 1
        faces.append([previous, current])
        previous = current

    total_length = sum(
        math.dist(vertices[face[0]], vertices[face[1]]) for face in faces
    )
    geometry = Geometry(
        name=f"{proposer}_meander_dipole",
        vertices=vertices,
        faces=faces,
        metadata={
            "antenna_class": "meander_dipole",
            "wire_radius_m": WIRE_RADIUS_M,
            "box_size_m": WIRE_BOX_SIZE_M,
            "minimum_pitch_m": pitch,
            "feed_gap_m": gap,
            "turn_count": turns,
            "total_wire_length_m": total_length,
            "target_total_wire_length_m": parameters.get("total_length_m"),
            "design_features": dict(parameters),
        },
    )
    return geometry


def build_box_straight_dipole(proposer: str = "classic") -> Geometry:
    """Build the longest axis-aligned straight dipole in the fixed 30 mm box."""

    length = WIRE_BOX_SIZE_M
    return Geometry(
        name=f"{proposer}_box_straight_dipole",
        vertices=[[-length / 2.0, 0.0, 0.0], [length / 2.0, 0.0, 0.0]],
        faces=[[0, 1]],
        metadata={
            "antenna_class": "box_straight_dipole",
            "wire_radius_m": WIRE_RADIUS_M,
            "box_size_m": WIRE_BOX_SIZE_M,
            "total_wire_length_m": length,
            "reference_definition": "longest_axis_aligned_straight_dipole",
        },
    )


def validate_meander_geometry(geometry: Geometry) -> None:
    """Reject unmanufacturable or out-of-box centerlines before simulation."""

    if geometry.metadata.get("antenna_class") != "meander_dipole":
        raise ValueError("wire proposal is not a meander_dipole")
    if not geometry.vertices or not geometry.faces:
        raise ValueError("meander must contain vertices and wire edges")
    if any(len(face) != 2 for face in geometry.faces):
        raise ValueError("meander geometry may contain only two-node wire edges")
    for vertex in geometry.vertices:
        if abs(vertex[0]) > WIRE_HALF_BOX_M + 1e-12:
            raise ValueError("meander exceeds the 30 mm x boundary")
        if abs(vertex[1]) > WIRE_HALF_BOX_M + 1e-12:
            raise ValueError("meander exceeds the 30 mm y boundary")
        if abs(vertex[2]) > 1e-12:
            raise ValueError("meander must remain planar")
    pitch = float(geometry.metadata.get("minimum_pitch_m", 0.0))
    if pitch < MINIMUM_PITCH_M - 1e-12:
        raise ValueError(
            f"meander pitch {pitch} is below manufacturable minimum {MINIMUM_PITCH_M}"
        )
    total_length = float(geometry.metadata.get("total_wire_length_m", 0.0))
    if total_length <= 0.0 or total_length > MAXIMUM_TOTAL_WIRE_LENGTH_M:
        raise ValueError("meander total wire length is outside the frozen safe range")
    target_length = geometry.metadata.get("target_total_wire_length_m")
    if target_length is not None and not math.isclose(
        total_length, float(target_length), rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("meander geometry does not realize its requested wire length")
    for face in geometry.faces:
        length = math.dist(geometry.vertices[face[0]], geometry.vertices[face[1]])
        if length < 4.0 * WIRE_RADIUS_M - 1e-12:
            raise ValueError("meander contains a segment shorter than four wire radii")


def reflection_magnitude_from_s11(min_s11_db: float) -> float:
    """Convert passive S11 in dB to a bounded voltage reflection magnitude."""

    if not math.isfinite(min_s11_db):
        raise ValueError("min_s11_db must be finite")
    return min(1.0, math.pow(10.0, min_s11_db / 20.0))


def realized_gain_dbi(raw_gain_dbi: float, min_s11_db: float) -> float:
    """Apply mismatch loss to accepted-power gain in a numerically stable way."""

    gamma = reflection_magnitude_from_s11(min_s11_db)
    mismatch_efficiency = max(
        1.0 - gamma * gamma,
        MINIMUM_MISMATCH_EFFICIENCY,
    )
    return raw_gain_dbi + 10.0 * math.log10(mismatch_efficiency)


def evaluate_wire_metrics(
    simulation: SimulationResult,
    spec: DesignSpec,
) -> dict[str, float]:
    """Score wire results with realized gain and no lossless-efficiency weight."""

    if simulation.s_params is None or not simulation.s_params.s_matrix:
        raise ValueError("wire scoring requires an S11 curve")
    if simulation.gain_dbi is None:
        raise ValueError("wire scoring requires real-solver gain")
    s11_db = tuple(
        20.0 * math.log10(max(abs(row[0][0]), 1e-15))
        for row in simulation.s_params.s_matrix
    )
    resonance_index = min(range(len(s11_db)), key=s11_db.__getitem__)
    min_s11_db = s11_db[resonance_index]
    gamma = reflection_magnitude_from_s11(min_s11_db)
    mismatch_efficiency = max(0.0, 1.0 - gamma * gamma)
    realized = realized_gain_dbi(simulation.gain_dbi, min_s11_db)
    target_gain = spec.target_gain_dbi or WIRE_GAIN_TARGET_DBI
    gain_score = min(1.0, 10.0 ** ((realized - target_gain) / 10.0))
    best_vswr = (
        (1.0 + gamma) / (1.0 - gamma) if gamma < 1.0 else float("inf")
    )
    target_vswr = spec.target_vswr or 2.0
    vswr_score = min(1.0, target_vswr / best_vswr)
    score = (gain_score + 0.5 * vswr_score) / 1.5
    return {
        "composite_score": score,
        "gain_dbi": simulation.gain_dbi,
        "realized_gain_dbi": realized,
        "mismatch_efficiency": mismatch_efficiency,
        "vswr": best_vswr,
        "efficiency": simulation.efficiency or 0.0,
        "efficiency_weight": 0.0,
        "min_s11_db": min_s11_db,
        "resonance_index": float(resonance_index),
        "resonance_frequency_hz": simulation.s_params.frequency[resonance_index],
    }


def wire_spec_updates() -> dict[str, Any]:
    """Return the fixed 30 mm bounding-box update for the wifi24 registered spec."""

    return {
        "name": "wifi24_wire_exploration",
        "size_constraint": BoundingBox(
            x_min=-WIRE_HALF_BOX_M,
            x_max=WIRE_HALF_BOX_M,
            y_min=-WIRE_HALF_BOX_M,
            y_max=WIRE_HALF_BOX_M,
            z_min=-0.001,
            z_max=0.001,
        ),
        "material_palette": ["copper"],
        "target_gain_dbi": WIRE_GAIN_TARGET_DBI,
        "efficiency_target": None,
    }
