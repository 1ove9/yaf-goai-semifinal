"""Frozen resource gates and extrapolation for the final patch cross-check."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

SOURCE_RUN_ID = "day2-wifi24-gp-s505"
SOURCE_DESIGN_INDEX = 0
SOURCE_STEP_INDEX = 16
SOURCE_GEOMETRY_HASH = (
    "61d215dd9b4e463e7d067f90f1612655ebed0a066f580f9817460c3d6659def1"
)
SOURCE_CROSSCHECK_RUN_ID = "day3-crosscheck-wifi24"
SOURCE_CONVERGENCE_RUN_ID = "day4-attribution-wifi24"
FREQUENCY_RANGE_HZ = (4098041023.321768, 6830068372.202946)
FREQUENCY_POINTS = 51
PATCH_GRID_LADDER = (32, 36, 44)
OPENEMS_REFINEMENT_LADDER = (2.0, 4.0)
MAX_SINGLE_RUN_SECONDS = 3.0 * 60.0 * 60.0
AVAILABLE_MEMORY_FRACTION_LIMIT = 0.80
TARGET_RESONANCE_GAP = 0.05
TARGET_PEARSON = 0.8

# Frozen empirical references from the completed wire study. Correlation is modeled
# linearly against log(gap), then mapped through the patch grid-gap power law.
WIRE_PEARSON_REFERENCES = (
    (0.04478, 0.719342),
    (0.011811023622047244, 0.9552994060520263),
)


class GridResourcePrediction(BaseModel):
    """Pre-run resource prediction evaluated against the frozen stop rules."""

    model_config = ConfigDict(frozen=True)

    target_grid_intervals: int = Field(gt=1)
    target_segment_count: int = Field(gt=0)
    baseline_grid_intervals: int = Field(gt=1)
    baseline_segment_count: int = Field(gt=0)
    baseline_actual_seconds: float = Field(gt=0.0)
    predicted_seconds: float = Field(gt=0.0)
    predicted_matrix_bytes: int = Field(gt=0)
    available_memory_bytes: int = Field(gt=0)
    memory_limit_bytes: int = Field(gt=0)
    time_limit_seconds: float = MAX_SINGLE_RUN_SECONDS
    memory_fraction_limit: float = AVAILABLE_MEMORY_FRACTION_LIMIT
    time_feasible: bool
    memory_feasible: bool
    feasible: bool


def grid_segment_count(grid_intervals: int) -> int:
    """Return exact feed-plus-two-plane segment count for the frozen grid mapping."""

    if grid_intervals <= 1:
        raise ValueError("grid_intervals must exceed one")
    return 4 * grid_intervals * (grid_intervals + 1) + 1


def dense_complex_matrix_bytes(segment_count: int) -> int:
    """Estimate one dense complex128 NEC2 interaction matrix."""

    if segment_count <= 0:
        raise ValueError("segment_count must be positive")
    return segment_count * segment_count * 16


def predict_cubic_runtime_seconds(
    *,
    baseline_grid_intervals: int,
    baseline_actual_seconds: float,
    target_grid_intervals: int,
) -> float:
    """Scale measured NEC2 time by the cube of the exact segment-count ratio."""

    if baseline_actual_seconds <= 0.0:
        raise ValueError("baseline_actual_seconds must be positive")
    baseline_segments = grid_segment_count(baseline_grid_intervals)
    target_segments = grid_segment_count(target_grid_intervals)
    return baseline_actual_seconds * (target_segments / baseline_segments) ** 3


def resources_feasible(
    *,
    predicted_seconds: float,
    predicted_matrix_bytes: int,
    available_memory_bytes: int,
) -> tuple[bool, bool, bool]:
    """Apply inclusive 3-hour and 80%-of-available-memory limits."""

    if predicted_seconds <= 0.0:
        raise ValueError("predicted_seconds must be positive")
    if predicted_matrix_bytes <= 0 or available_memory_bytes <= 0:
        raise ValueError("memory byte counts must be positive")
    time_ok = predicted_seconds <= MAX_SINGLE_RUN_SECONDS
    memory_ok = predicted_matrix_bytes <= int(
        available_memory_bytes * AVAILABLE_MEMORY_FRACTION_LIMIT
    )
    return time_ok, memory_ok, time_ok and memory_ok


def predict_grid_resources(
    *,
    baseline_grid_intervals: int,
    baseline_actual_seconds: float,
    target_grid_intervals: int,
    available_memory_bytes: int,
) -> GridResourcePrediction:
    """Build the complete auditable prediction made immediately before a run."""

    baseline_segments = grid_segment_count(baseline_grid_intervals)
    target_segments = grid_segment_count(target_grid_intervals)
    predicted_seconds = predict_cubic_runtime_seconds(
        baseline_grid_intervals=baseline_grid_intervals,
        baseline_actual_seconds=baseline_actual_seconds,
        target_grid_intervals=target_grid_intervals,
    )
    matrix_bytes = dense_complex_matrix_bytes(target_segments)
    time_ok, memory_ok, feasible = resources_feasible(
        predicted_seconds=predicted_seconds,
        predicted_matrix_bytes=matrix_bytes,
        available_memory_bytes=available_memory_bytes,
    )
    return GridResourcePrediction(
        target_grid_intervals=target_grid_intervals,
        target_segment_count=target_segments,
        baseline_grid_intervals=baseline_grid_intervals,
        baseline_segment_count=baseline_segments,
        baseline_actual_seconds=baseline_actual_seconds,
        predicted_seconds=predicted_seconds,
        predicted_matrix_bytes=matrix_bytes,
        available_memory_bytes=available_memory_bytes,
        memory_limit_bytes=int(
            available_memory_bytes * AVAILABLE_MEMORY_FRACTION_LIMIT
        ),
        time_feasible=time_ok,
        memory_feasible=memory_ok,
        feasible=feasible,
    )


def predict_openems_runtime_seconds(
    *,
    baseline_refinement: float,
    baseline_actual_seconds: float,
    target_refinement: float,
) -> float:
    """Conservatively scale FDTD time with the fourth power of mesh refinement."""

    if (
        baseline_refinement <= 0.0
        or baseline_actual_seconds <= 0.0
        or target_refinement <= 0.0
    ):
        raise ValueError("openEMS refinements and time must be positive")
    return baseline_actual_seconds * (target_refinement / baseline_refinement) ** 4


def power_law_grid_estimate(
    grids: Sequence[int],
    gaps: Sequence[float],
    *,
    target_gap: float = TARGET_RESONANCE_GAP,
) -> int | None:
    """Refit gap=A*grid**(-p) using every completed positive monotonic point."""

    if len(grids) != len(gaps) or len(grids) < 2:
        raise ValueError("power-law extrapolation requires aligned points")
    if target_gap <= 0.0 or any(grid <= 1 for grid in grids):
        raise ValueError("grid and target gap are outside their valid range")
    if any(gap <= 0.0 for gap in gaps) or any(
        left < right for left, right in zip(gaps, gaps[1:], strict=False)
    ):
        return None
    slope, intercept = np.polyfit(
        np.log(np.asarray(grids, dtype=float)),
        np.log(np.asarray(gaps, dtype=float)),
        1,
    )
    exponent = -float(slope)
    if exponent <= 0.0:
        return None
    coefficient = math.exp(float(intercept))
    estimate = int(math.ceil((coefficient / target_gap) ** (1.0 / exponent)))
    return max(int(grids[-1]) + 1, estimate)


def wire_reference_gap_for_pearson(
    target_pearson: float = TARGET_PEARSON,
) -> float | None:
    """Map Pearson to a gap using the frozen two-point wire reference in log-gap."""

    first, second = WIRE_PEARSON_REFERENCES
    low_correlation = min(first[1], second[1])
    high_correlation = max(first[1], second[1])
    if not low_correlation <= target_pearson <= high_correlation:
        return None
    slope = (second[1] - first[1]) / (math.log(second[0]) - math.log(first[0]))
    intercept = first[1] - slope * math.log(first[0])
    if slope == 0.0:
        return None
    return math.exp((target_pearson - intercept) / slope)


def grid_estimate_for_pearson(
    grids: Sequence[int], gaps: Sequence[float]
) -> int | None:
    """Translate the wire-derived Pearson gap target through the patch trend."""

    target_gap = wire_reference_gap_for_pearson()
    if target_gap is None:
        return None
    return power_law_grid_estimate(grids, gaps, target_gap=target_gap)
