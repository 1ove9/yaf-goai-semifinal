"""Regression tests for corrected wire metrics and protocol v2.1."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from yaf_ai.exploration.cross_check import SolverCurve
from yaf_ai.exploration.cross_check_v21 import (
    evaluate_curves_v21,
    resonance_validity,
)
from yaf_ai.exploration.wire import realized_gain_dbi
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter


def _curve(
    values: tuple[float, ...], *, solver_name: str = "nec2"
) -> SolverCurve:
    frequencies = tuple(1.5e9 + index * 10e6 for index in range(len(values)))
    minimum = min(range(len(values)), key=values.__getitem__)
    return SolverCurve(
        solver_name=solver_name,
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=values,
        resonance_frequency_hz=frequencies[minimum],
        resonance_s11_db=values[minimum],
        simulation_time_seconds=0.1,
    )


def test_realized_gain_applies_mismatch_loss() -> None:
    expected = 2.15 + 10.0 * math.log10(0.9)
    assert realized_gain_dbi(2.15, -10.0) == pytest.approx(expected)


def test_realized_gain_tends_to_negative_infinity_as_gamma_tends_to_one() -> None:
    near_total_reflection = realized_gain_dbi(6.23, -1e-9)
    exact_total_reflection = realized_gain_dbi(6.23, 0.0)
    assert near_total_reflection < -80.0
    assert exact_total_reflection < -2900.0


@pytest.mark.parametrize(
    ("minimum_index", "minimum_db", "expected"),
    (
        (3, -6.1, True),
        (2, -6.1, False),
        (7, -6.1, False),
        (3, -5.9, False),
    ),
)
def test_resonance_validity_boundaries(
    minimum_index: int, minimum_db: float, expected: bool
) -> None:
    values = [-1.0] * 10
    values[minimum_index] = minimum_db
    assert resonance_validity(_curve(tuple(values))).valid is expected


def test_invalid_curve_cannot_reach_agreement_metrics() -> None:
    flat = _curve((-0.1, -0.09, -0.08, -0.07, -0.06, -0.05), solver_name="openems")
    valid = _curve((-1.0, -2.0, -4.0, -8.0, -4.0, -2.0), solver_name="nec2")
    decision = evaluate_curves_v21(flat, valid)
    assert decision.verdict == "NO_RESONANCE_IN_BAND"
    assert decision.resonance_relative_difference is None
    assert decision.curve_pearson_correlation is None


def test_real_nec2_half_wave_fixture_has_known_gain() -> None:
    fixture = (
        Path(__file__).parents[1] / "fixtures" / "nec2" / "half_wave_2450_real.out"
    )
    result = NEC2Adapter()._result_from_nec_text(
        fixture.read_text(encoding="utf-8"),
        "00000000-0000-0000-0000-000000000001",
        f_center=2.45e9,
    )
    assert result.gain_dbi == pytest.approx(2.15, abs=0.3)
    assert result.gain_dbi == pytest.approx(2.19)
    assert result.efficiency == pytest.approx(1.0)
