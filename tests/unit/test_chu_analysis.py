"""Known-answer tests for Chu and loaded-Q archive analysis primitives."""

from __future__ import annotations

import math

import numpy as np
import pytest

from yaf_ai.analysis.chu import (
    fit_rlc_q,
    fractional_bandwidth_q,
    mclean_q_min,
    minimum_enclosing_sphere,
    rlc_reflected_power,
)


def test_mclean_known_value_at_ka_one() -> None:
    assert mclean_q_min(1.0) == pytest.approx(2.0)


def test_minimum_enclosing_sphere_for_planar_rectangle() -> None:
    points = [
        (-1.0, -2.0, 0.0),
        (-1.0, 2.0, 0.0),
        (1.0, -2.0, 0.0),
        (1.0, 2.0, 0.0),
        (0.0, 0.0, 0.0),
    ]
    sphere = minimum_enclosing_sphere(points)
    assert sphere.center_m == pytest.approx((0.0, 0.0, 0.0))
    assert sphere.radius_m == pytest.approx(math.sqrt(5.0))


@pytest.mark.parametrize("known_q", [20.0, 50.0, 100.0])
def test_synthetic_rlc_q_recovery_within_five_percent(known_q: float) -> None:
    resonance = 2.45e9
    frequencies = np.linspace(0.90 * resonance, 1.10 * resonance, 4001)
    power = rlc_reflected_power(frequencies, 0.01, resonance, known_q)
    s11_db = 10.0 * np.log10(power)
    fitted = fit_rlc_q(frequencies, s11_db)
    assert fitted.q_loaded == pytest.approx(known_q, rel=0.05)
    assert fitted.r_squared > 0.999
    assert fitted.confidence == "high_confidence"


def test_fractional_bandwidth_matches_synthetic_rlc() -> None:
    resonance = 2.45e9
    known_q = 50.0
    frequencies = np.linspace(0.95 * resonance, 1.05 * resonance, 4001)
    power = rlc_reflected_power(frequencies, 0.04, resonance, known_q)
    fitted = fit_rlc_q(frequencies, 10.0 * np.log10(power))
    q_bandwidth, fractional = fractional_bandwidth_q(
        fitted.fitted_resonance_hz,
        fitted.window.left_crossing_hz,
        fitted.window.right_crossing_hz,
    )
    assert q_bandwidth == pytest.approx(known_q, rel=0.01)
    assert fractional == pytest.approx(1.0 / known_q, rel=0.01)
    assert not fitted.bandwidth_disagreement_over_30pct
