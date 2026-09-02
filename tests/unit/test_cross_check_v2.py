"""Mock-only tests for the preregistered Day 4 cross-solver protocol."""

from __future__ import annotations

import math

import pytest

from yaf_ai.exploration.cross_check import AirVariantDefinition, SolverCurve
from yaf_ai.exploration.cross_check_v2 import (
    ConvergencePoint,
    build_wire_grid,
    curve_correlation,
    evaluate_attribution,
    evaluate_curves,
)


def _curve(frequencies: tuple[float, ...], values: tuple[float, ...]) -> SolverCurve:
    index = min(range(len(values)), key=values.__getitem__)
    return SolverCurve(
        solver_name="mock",
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=values,
        resonance_frequency_hz=frequencies[index],
        resonance_s11_db=values[index],
        simulation_time_seconds=0.1,
    )


def _point(grid: int, gap: float) -> ConvergencePoint:
    curve = _curve((1.0, 2.0, 3.0), (-1.0, -2.0, -1.0))
    return ConvergencePoint(
        grid_intervals=grid,
        nec2_resonance_frequency_hz=2.0 * (1.0 + gap),
        openems_reference_frequency_hz=2.0,
        resonance_relative_gap=gap,
        minimum_spacing_m=0.001,
        equal_area_wire_radius_m=0.0001,
        spacing_to_radius_ratio=10.0,
        segment_count=grid * grid,
        solve_time_seconds=0.1,
        curve=curve,
    )


def test_curve_correlation_interpolates_common_band() -> None:
    first = _curve((1.0, 2.0, 3.0), (-1.0, -5.0, -1.0))
    second = _curve((1.0, 1.5, 2.0, 2.5, 3.0), (-2.0, -4.0, -6.0, -4.0, -2.0))
    assert curve_correlation(first, second) == pytest.approx(1.0)


def test_depth_is_record_only_in_v2_decision() -> None:
    openems = _curve((1.0, 2.0, 3.0), (-1.0, -10.0, -1.0))
    nec2 = _curve((1.0, 2.0, 3.0), (-1.0, -50.0, -1.0))
    decision = evaluate_curves(openems, nec2)
    assert decision.verdict == "CONFIRMED"
    assert decision.s11_depth_difference_db == 40.0
    assert decision.s11_depth_is_record_only is True


def test_anchor_uses_stricter_thresholds() -> None:
    openems = _curve((1.0, 2.0, 3.0), (-1.0, -10.0, -1.0))
    nec2 = SolverCurve(
        solver_name="mock",
        solver_mode="subprocess",
        frequency_hz=(1.0, 2.08, 3.0),
        s11_db=(-1.0, -10.0, -1.0),
        resonance_frequency_hz=2.08,
        resonance_s11_db=-10.0,
        simulation_time_seconds=0.1,
    )
    assert evaluate_curves(openems, nec2).verdict == "CONFIRMED"
    assert evaluate_curves(openems, nec2, anchor=True).verdict == "DIVERGENT"


@pytest.mark.parametrize(
    ("gaps", "expected"),
    (
        ((0.30, 0.20, 0.10), "instrument_boundary"),
        ((0.30, 0.27, 0.25), "genuine_anomaly"),
        ((0.30, 0.22, 0.18), "inconclusive_needs_finer_grid"),
    ),
)
def test_frozen_attribution_boundaries(
    gaps: tuple[float, float, float], expected: str
) -> None:
    points = tuple(
        _point(grid, gap) for grid, gap in zip((6, 12, 24), gaps, strict=True)
    )
    decision = evaluate_attribution(points)
    assert decision.verdict == expected
    assert decision.estimated_grid_intervals_for_five_percent is not None


def test_dynamic_grid_preserves_equal_area_and_reports_spacing() -> None:
    definition = AirVariantDefinition(
        patch_length_m=0.03,
        patch_width_m=0.04,
        patch_metal_area_m2=0.0012,
        ground_length_m=0.045,
        ground_width_m=0.06,
        ground_metal_area_m2=0.0027,
        air_gap_m=0.0016,
        feed_x_m=-0.005,
        feed_y_m=0.0,
        original_eps_r=4.4,
    )
    _, grid, spacing = build_wire_grid(definition, 12)
    represented = (
        2.0
        * math.pi
        * grid.equal_area_wire_radius_m
        * grid.total_grid_wire_length_m
    )
    assert represented == pytest.approx(grid.represented_metal_area_m2)
    assert grid.grid_intervals == 12
    assert spacing > 0.0
