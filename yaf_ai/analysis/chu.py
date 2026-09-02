"""Chu--McLean electrical-size and archive-curve loaded-Q diagnostics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import combinations
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import least_squares

C0_M_PER_S = 299_792_458.0
EDGE_GUARD_SAMPLES = 3
RESONANCE_DEPTH_THRESHOLD_DB = -6.0
MINIMUM_FIT_POINTS = 5
R_SQUARED_THRESHOLD = 0.9
BANDWIDTH_DISAGREEMENT_THRESHOLD = 0.30
MAXIMUM_Q = 1_000_000.0
FloatSeries = Sequence[float] | NDArray[np.float64]


class EnclosingSphere(BaseModel):
    """Minimum sphere containing all supplied geometry vertices."""

    model_config = ConfigDict(frozen=True)

    center_m: tuple[float, float, float]
    radius_m: float = Field(ge=0.0)


class ResonanceWindow(BaseModel):
    """Frozen half-notch-power window and interpolated crossings."""

    model_config = ConfigDict(frozen=True)

    minimum_index: int = Field(ge=0)
    minimum_s11_db: float
    minimum_power: float = Field(ge=0.0)
    half_notch_power: float = Field(gt=0.0)
    start_index: int = Field(ge=0)
    stop_index: int = Field(ge=0)
    fit_point_count: int = Field(ge=2)
    left_crossing_hz: float = Field(gt=0.0)
    right_crossing_hz: float = Field(gt=0.0)


class QFitResult(BaseModel):
    """Primary RLC proxy plus fractional-bandwidth and sampling diagnostics."""

    model_config = ConfigDict(frozen=True)

    method: Literal["rlc_reflected_power_proxy"] = "rlc_reflected_power_proxy"
    q_loaded: float = Field(gt=0.0)
    fitted_resonance_hz: float = Field(gt=0.0)
    fitted_minimum_power: float = Field(ge=0.0, lt=1.0)
    r_squared: float
    confidence: Literal["high_confidence", "low_confidence"]
    window: ResonanceWindow
    q_fractional_bandwidth: float = Field(gt=0.0)
    fractional_bandwidth: float = Field(gt=0.0)
    bandwidth_disagreement_fraction: float = Field(ge=0.0)
    bandwidth_disagreement_over_30pct: bool
    sample_count: int = Field(ge=2)
    median_bin_width_hz: float = Field(gt=0.0)
    relative_bin_width: float = Field(gt=0.0)
    resonance_bin_uncertainty_hz: float = Field(gt=0.0)
    bandwidth_bin_uncertainty_hz: float = Field(gt=0.0)
    q_bandwidth_lower: float = Field(gt=0.0)
    q_bandwidth_upper: float | None = Field(default=None, gt=0.0)
    q_standard_error: float | None = Field(default=None, ge=0.0)
    combined_relative_uncertainty: float = Field(ge=0.0)


def mclean_q_min(ka: float) -> float:
    """Return McLean's linearly polarized 100%-efficiency Chu lower bound."""

    if not math.isfinite(ka) or ka <= 0.0:
        raise ValueError("ka must be finite and positive")
    return 1.0 / ka**3 + 1.0 / ka


def electrical_size(frequency_hz: float, radius_m: float) -> float:
    """Return ka using the fitted resonance frequency and enclosing radius."""

    if not math.isfinite(frequency_hz) or frequency_hz <= 0.0:
        raise ValueError("frequency_hz must be finite and positive")
    if not math.isfinite(radius_m) or radius_m <= 0.0:
        raise ValueError("radius_m must be finite and positive")
    return 2.0 * math.pi * frequency_hz * radius_m / C0_M_PER_S


def _sphere_from_boundary(points: NDArray[np.float64]) -> EnclosingSphere | None:
    origin = points[0]
    if len(points) == 1:
        return EnclosingSphere(center_m=tuple(float(v) for v in origin), radius_m=0.0)
    offsets = points[1:] - origin
    if np.linalg.matrix_rank(offsets) != len(points) - 1:
        return None
    gram = offsets @ offsets.T
    coefficients = np.linalg.solve(gram, 0.5 * np.diag(gram))
    center = origin + offsets.T @ coefficients
    radius = float(np.linalg.norm(center - origin))
    return EnclosingSphere(
        center_m=tuple(float(value) for value in center),
        radius_m=radius,
    )


def minimum_enclosing_sphere(
    points: Sequence[Sequence[float]],
) -> EnclosingSphere:
    """Find the exact finite-point minimum sphere by boundary enumeration."""

    array = np.asarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 3 or len(array) == 0:
        raise ValueError("points must be a nonempty Nx3 sequence")
    if not np.isfinite(array).all():
        raise ValueError("points must be finite")
    unique = np.unique(array, axis=0)
    scale = max(float(np.max(np.linalg.norm(unique, axis=1))), 1.0)
    tolerance = scale * 1e-10
    best: EnclosingSphere | None = None
    for boundary_size in range(1, min(4, len(unique)) + 1):
        for indices in combinations(range(len(unique)), boundary_size):
            candidate = _sphere_from_boundary(unique[list(indices)])
            if candidate is None:
                continue
            center = np.asarray(candidate.center_m, dtype=np.float64)
            distances = np.linalg.norm(unique - center, axis=1)
            if np.any(distances > candidate.radius_m + tolerance):
                continue
            if best is None or candidate.radius_m < best.radius_m:
                best = candidate
    if best is None:
        raise ValueError("cannot construct a finite enclosing sphere")
    return best


def rlc_reflected_power(
    frequency_hz: NDArray[np.float64],
    minimum_power: float,
    resonance_hz: float,
    q_loaded: float,
) -> NDArray[np.float64]:
    """Evaluate the preregistered magnitude-only series-RLC power proxy."""

    ratio = frequency_hz / resonance_hz
    detuning = q_loaded * (ratio - 1.0 / ratio)
    return minimum_power + (1.0 - minimum_power) * (
        detuning * detuning / (1.0 + detuning * detuning)
    )


def _interpolate_crossing(
    first_frequency: float,
    first_power: float,
    second_frequency: float,
    second_power: float,
    threshold: float,
) -> float:
    delta = second_power - first_power
    if delta == 0.0:
        return (first_frequency + second_frequency) / 2.0
    fraction = (threshold - first_power) / delta
    return first_frequency + fraction * (second_frequency - first_frequency)


def resonance_window(
    frequency_hz: FloatSeries, s11_db: FloatSeries
) -> ResonanceWindow:
    """Select the frozen half-notch-power fitting window or reject the curve."""

    frequencies = np.asarray(frequency_hz, dtype=np.float64)
    values_db = np.asarray(s11_db, dtype=np.float64)
    if (
        frequencies.ndim != 1
        or values_db.ndim != 1
        or len(frequencies) != len(values_db)
        or len(frequencies) < 2 * EDGE_GUARD_SAMPLES + 1
    ):
        raise ValueError("frequency and S11 arrays have incompatible sizes")
    if not np.isfinite(frequencies).all() or not np.isfinite(values_db).all():
        raise ValueError("frequency and S11 arrays must be finite")
    if np.any(np.diff(frequencies) <= 0.0):
        raise ValueError("frequency samples must be strictly increasing")
    minimum_index = int(np.argmin(values_db))
    if not (
        EDGE_GUARD_SAMPLES
        <= minimum_index
        < len(frequencies) - EDGE_GUARD_SAMPLES
    ):
        raise ValueError("resonance minimum is inside the frozen edge guard")
    minimum_s11_db = float(values_db[minimum_index])
    if minimum_s11_db > RESONANCE_DEPTH_THRESHOLD_DB:
        raise ValueError("resonance minimum does not reach -6 dB")
    powers = np.power(10.0, values_db / 10.0)
    minimum_power = float(powers[minimum_index])
    half_notch_power = (1.0 + minimum_power) / 2.0

    left_index: int | None = None
    for index in range(minimum_index - 1, -1, -1):
        if powers[index] >= half_notch_power:
            left_index = index
            break
    right_index: int | None = None
    for index in range(minimum_index + 1, len(powers)):
        if powers[index] >= half_notch_power:
            right_index = index
            break
    if left_index is None or right_index is None:
        raise ValueError("half-notch-power crossing is missing on one or both sides")
    fit_point_count = right_index - left_index + 1
    if fit_point_count < MINIMUM_FIT_POINTS:
        raise ValueError("half-notch-power window contains fewer than five samples")
    left_crossing = _interpolate_crossing(
        float(frequencies[left_index]),
        float(powers[left_index]),
        float(frequencies[left_index + 1]),
        float(powers[left_index + 1]),
        half_notch_power,
    )
    right_crossing = _interpolate_crossing(
        float(frequencies[right_index - 1]),
        float(powers[right_index - 1]),
        float(frequencies[right_index]),
        float(powers[right_index]),
        half_notch_power,
    )
    return ResonanceWindow(
        minimum_index=minimum_index,
        minimum_s11_db=minimum_s11_db,
        minimum_power=minimum_power,
        half_notch_power=half_notch_power,
        start_index=left_index,
        stop_index=right_index,
        fit_point_count=fit_point_count,
        left_crossing_hz=left_crossing,
        right_crossing_hz=right_crossing,
    )


def fractional_bandwidth_q(
    resonance_hz: float, left_crossing_hz: float, right_crossing_hz: float
) -> tuple[float, float]:
    """Return Q_FBW and fractional bandwidth from frozen power crossings."""

    bandwidth = right_crossing_hz - left_crossing_hz
    if resonance_hz <= 0.0 or bandwidth <= 0.0:
        raise ValueError("resonance and crossing bandwidth must be positive")
    fractional_bandwidth = bandwidth / resonance_hz
    return 1.0 / fractional_bandwidth, fractional_bandwidth


def fit_rlc_q(
    frequency_hz: FloatSeries, s11_db: FloatSeries
) -> QFitResult:
    """Fit the frozen loaded-Q proxy and attach bandwidth/bin diagnostics."""

    frequencies = np.asarray(frequency_hz, dtype=np.float64)
    values_db = np.asarray(s11_db, dtype=np.float64)
    window = resonance_window(frequencies, values_db)
    start = window.start_index
    stop = window.stop_index + 1
    fit_frequencies = frequencies[start:stop]
    fit_power = np.power(10.0, values_db[start:stop] / 10.0)
    scale_hz = float(frequencies[window.minimum_index])
    normalized_frequencies = fit_frequencies / scale_hz
    q_initial, _fractional_initial = fractional_bandwidth_q(
        scale_hz, window.left_crossing_hz, window.right_crossing_hz
    )

    def residual(parameters: NDArray[np.float64]) -> NDArray[np.float64]:
        minimum_power, normalized_resonance, q_loaded = parameters
        model = rlc_reflected_power(
            normalized_frequencies,
            float(minimum_power),
            float(normalized_resonance),
            float(q_loaded),
        )
        return model - fit_power

    lower = np.asarray(
        [0.0, float(fit_frequencies[0] / scale_hz), 1e-9],
        dtype=np.float64,
    )
    upper = np.asarray(
        [1.0 - 1e-12, float(fit_frequencies[-1] / scale_hz), MAXIMUM_Q],
        dtype=np.float64,
    )
    initial = np.asarray(
        [window.minimum_power, 1.0, min(q_initial, MAXIMUM_Q * 0.9)],
        dtype=np.float64,
    )
    result = least_squares(
        residual,
        initial,
        bounds=(lower, upper),
        x_scale="jac",
        ftol=1e-13,
        xtol=1e-13,
        gtol=1e-13,
        max_nfev=10_000,
    )
    if not result.success or not np.isfinite(result.x).all():
        raise ValueError(f"RLC proxy fit failed: {result.message}")
    minimum_power = float(result.x[0])
    fitted_resonance_hz = float(result.x[1] * scale_hz)
    q_loaded = float(result.x[2])
    residuals = np.asarray(result.fun, dtype=np.float64)
    sum_squared_error = float(residuals @ residuals)
    centered = fit_power - float(np.mean(fit_power))
    total_sum_squares = float(centered @ centered)
    r_squared = (
        1.0 - sum_squared_error / total_sum_squares
        if total_sum_squares > 0.0
        else float("-inf")
    )
    q_bandwidth, fractional_bandwidth = fractional_bandwidth_q(
        fitted_resonance_hz,
        window.left_crossing_hz,
        window.right_crossing_hz,
    )
    disagreement = abs(q_loaded - q_bandwidth) / q_loaded
    bins = np.diff(frequencies)
    bin_width = float(np.median(bins))
    bandwidth = window.right_crossing_hz - window.left_crossing_hz
    q_bandwidth_lower = fitted_resonance_hz / (bandwidth + bin_width)
    q_bandwidth_upper = (
        fitted_resonance_hz / (bandwidth - bin_width)
        if bandwidth > bin_width
        else None
    )

    q_standard_error: float | None = None
    jacobian = np.asarray(result.jac, dtype=np.float64)
    degrees_of_freedom = len(fit_power) - len(result.x)
    if degrees_of_freedom > 0 and np.linalg.matrix_rank(jacobian) == len(result.x):
        covariance = (
            np.linalg.inv(jacobian.T @ jacobian)
            * sum_squared_error
            / degrees_of_freedom
        )
        variance = float(covariance[2, 2])
        if variance >= 0.0 and math.isfinite(variance):
            q_standard_error = math.sqrt(variance)
    standard_relative = (
        q_standard_error / q_loaded if q_standard_error is not None else 0.0
    )
    bin_relative = bin_width / bandwidth
    combined_relative = math.hypot(standard_relative, bin_relative)
    confidence: Literal["high_confidence", "low_confidence"] = (
        "high_confidence"
        if r_squared >= R_SQUARED_THRESHOLD
        else "low_confidence"
    )
    return QFitResult(
        q_loaded=q_loaded,
        fitted_resonance_hz=fitted_resonance_hz,
        fitted_minimum_power=minimum_power,
        r_squared=r_squared,
        confidence=confidence,
        window=window,
        q_fractional_bandwidth=q_bandwidth,
        fractional_bandwidth=fractional_bandwidth,
        bandwidth_disagreement_fraction=disagreement,
        bandwidth_disagreement_over_30pct=(
            disagreement > BANDWIDTH_DISAGREEMENT_THRESHOLD
        ),
        sample_count=len(frequencies),
        median_bin_width_hz=bin_width,
        relative_bin_width=bin_width / fitted_resonance_hz,
        resonance_bin_uncertainty_hz=bin_width / 2.0,
        bandwidth_bin_uncertainty_hz=bin_width,
        q_bandwidth_lower=q_bandwidth_lower,
        q_bandwidth_upper=q_bandwidth_upper,
        q_standard_error=q_standard_error,
        combined_relative_uncertainty=combined_relative,
    )
