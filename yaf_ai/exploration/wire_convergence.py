"""Pre-registered attribution rules for meander segmentation convergence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AttributionVerdict = Literal[
    "instrument_boundary",
    "genuine_anomaly",
    "inconclusive_needs_finer_segmentation",
]


class SegmentationAttribution(BaseModel):
    """Deterministic outcome of the frozen lambda/20, /40, /80 study."""

    model_config = ConfigDict(frozen=True)

    verdict: AttributionVerdict
    monotonically_narrowing: bool
    finest_to_coarsest_ratio: float = Field(ge=0.0)
    estimated_segments_per_wavelength_for_five_percent: float | None = Field(
        default=None, gt=0.0
    )


def _extrapolated_density(
    densities: Sequence[int], gaps: Sequence[float]
) -> float | None:
    """Fit gap against inverse density and estimate the 5% crossing."""

    x = [1.0 / density for density in densities]
    x_mean = sum(x) / len(x)
    y_mean = sum(gaps) / len(gaps)
    denominator = sum((value - x_mean) ** 2 for value in x)
    if denominator == 0.0:
        return None
    slope = sum(
        (x_value - x_mean) * (gap - y_mean)
        for x_value, gap in zip(x, gaps, strict=True)
    ) / denominator
    intercept = y_mean - slope * x_mean
    if slope <= 0.0 or intercept >= 0.05:
        return None
    inverse_density = (0.05 - intercept) / slope
    if inverse_density <= 0.0:
        return None
    density = 1.0 / inverse_density
    return density if density > max(densities) else None


def classify_segmentation_convergence(
    gaps: Sequence[float],
    *,
    densities: Sequence[int] = (20, 40, 80),
) -> SegmentationAttribution:
    """Apply the frozen Day 5 attribution thresholds to resonance gaps."""

    if len(gaps) != 3 or len(densities) != 3:
        raise ValueError("convergence attribution requires exactly three levels")
    if any(gap < 0.0 for gap in gaps):
        raise ValueError("resonance gaps cannot be negative")
    if any(density <= 0 for density in densities):
        raise ValueError("segmentation densities must be positive")
    ratio = (
        (0.0 if gaps[-1] == 0.0 else float("inf"))
        if gaps[0] == 0.0
        else gaps[-1] / gaps[0]
    )
    monotonic = gaps[0] >= gaps[1] >= gaps[2]
    if monotonic and ratio < 0.5:
        verdict: AttributionVerdict = "instrument_boundary"
    elif ratio >= 0.8:
        verdict = "genuine_anomaly"
    else:
        verdict = "inconclusive_needs_finer_segmentation"
    estimate = (
        _extrapolated_density(densities, gaps)
        if verdict == "inconclusive_needs_finer_segmentation"
        else None
    )
    return SegmentationAttribution(
        verdict=verdict,
        monotonically_narrowing=monotonic,
        finest_to_coarsest_ratio=ratio,
        estimated_segments_per_wavelength_for_five_percent=estimate,
    )
