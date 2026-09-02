"""Boundary and byte-difference tests for Day 6.5 diagnostics."""

from __future__ import annotations

import pytest

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.day65_diagnostics import (
    classify_compute_feasibility,
    classify_radius_attribution,
    estimated_field_memory_bytes,
    validate_radius_only_deck_change,
)


@pytest.mark.parametrize(
    ("fraction", "classification"),
    [
        (0.299999, "attribution_not_supported"),
        (0.3, "partial_attribution"),
        (0.799999, "partial_attribution"),
        (0.8, "surrogate_radius_systematic_effect"),
    ],
)
def test_radius_attribution_boundaries(
    fraction: float, classification: str
) -> None:
    assert classify_radius_attribution(fraction).classification == classification


@pytest.mark.parametrize(
    ("ratio", "classification", "timeout"),
    [
        (1.349999, "future_timeout_extension_authorized", 43_200.0),
        (1.35, "infeasible_at_current_compute", None),
    ],
)
def test_compute_feasibility_boundary(
    ratio: float, classification: str, timeout: float | None
) -> None:
    result = classify_compute_feasibility(ratio)
    assert result.classification == classification
    assert result.future_timeout_seconds == timeout
    assert result.retry_in_this_task is False


def test_compute_feasibility_rejects_nonpositive_ratio() -> None:
    with pytest.raises(ValueError, match="positive"):
        classify_compute_feasibility(0.0)


def test_memory_estimate_is_disclosed_six_float64_fields() -> None:
    assert estimated_field_memory_bytes(10) == 10 * 6 * 8
    with pytest.raises(ValueError, match="positive"):
        estimated_field_memory_bytes(0)


def test_nec_deck_audit_accepts_only_gw_radius_changes() -> None:
    baseline = (
        b"CM same\nCE\n"
        b"GW   1    11 0 0 0 1 0 0 5.00000E-05\n"
        b"GW   2    11 1 0 0 2 0 0 5.00000E-05\n"
        b"GE 0\nEN"
    )
    tested = (
        b"CM same\nCE\n"
        b"GW   1    11 0 0 0 1 0 0 2.50000E-04\n"
        b"GW   2    11 1 0 0 2 0 0 2.50000E-04\n"
        b"GE 0\nEN"
    )
    assert validate_radius_only_deck_change(baseline, tested) == 2


def test_nec_deck_audit_rejects_nonradius_change() -> None:
    baseline = b"CM same\nCE\nGW 1 11 0 0 0 1 0 0 5.00000E-05\nGE 0\nEN"
    changed = b"CM same\nCE\nGW 1 13 0 0 0 1 0 0 2.50000E-04\nGE 0\nEN"
    with pytest.raises(CrossCheckError, match="outside GW radius"):
        validate_radius_only_deck_change(baseline, changed)
