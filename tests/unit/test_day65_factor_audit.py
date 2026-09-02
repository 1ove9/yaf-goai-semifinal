"""Unit tests for the preregistered Day 6.5 factorial audit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yaf_ai.exploration.day65 import DAY65_DIPOLE_LENGTH_M
from yaf_ai.exploration.day65_factor_audit import (
    BASELINE_NEC2_THICK_FREQUENCY_HZ,
    MATERIAL_SHIFT_HZ,
    SEGMENT_STABILITY_HZ,
    SHORTENED_CENTERLINE_LENGTH_M,
    build_factor_anchor_geometry,
    classify_materiality,
    classify_segmentation_stability,
    residual_bias,
)


@pytest.mark.parametrize(
    ("shift_hz", "expected"),
    [
        (MATERIAL_SHIFT_HZ - 1.0, "minor"),
        (MATERIAL_SHIFT_HZ, "material"),
        (-MATERIAL_SHIFT_HZ, "material"),
    ],
)
def test_materiality_inclusive_boundary(shift_hz: float, expected: str) -> None:
    assert classify_materiality(shift_hz) == expected


def test_materiality_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        classify_materiality(float("nan"))


def test_segmentation_stability_inclusive_boundary() -> None:
    decision = classify_segmentation_stability(
        BASELINE_NEC2_THICK_FREQUENCY_HZ - SEGMENT_STABILITY_HZ,
        BASELINE_NEC2_THICK_FREQUENCY_HZ + SEGMENT_STABILITY_HZ,
    )
    assert decision.maximum_shift_hz == SEGMENT_STABILITY_HZ
    assert decision.classification == "segmentation_stable"


def test_segmentation_instability_above_boundary() -> None:
    decision = classify_segmentation_stability(
        BASELINE_NEC2_THICK_FREQUENCY_HZ,
        BASELINE_NEC2_THICK_FREQUENCY_HZ + SEGMENT_STABILITY_HZ + 1.0,
    )
    assert decision.classification == "nec2_thick_wire_not_converged"


def test_factor_nec2_thick_anchor_matches_archived_radius_run() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    summary_path = (
        repo_root
        / "artifacts/runs/day65-nec2-surrogate-radius-diagnostic/summary.json"
    )
    archived = json.loads(summary_path.read_text(encoding="utf-8"))
    assert archived["resonance"]["frequency_hz"] == BASELINE_NEC2_THICK_FREQUENCY_HZ


def test_endcap_geometry_changes_only_free_ends_and_length() -> None:
    baseline = build_factor_anchor_geometry()
    shortened = build_factor_anchor_geometry(shorten_each_end_m=0.00025)
    assert shortened.vertices[0][0] == baseline.vertices[0][0]
    assert shortened.vertices[1] == baseline.vertices[1]
    assert shortened.vertices[2][0] == baseline.vertices[2][0]
    assert shortened.vertices[3][0] == baseline.vertices[3][0]
    assert shortened.vertices[2][1] == pytest.approx(baseline.vertices[2][1] - 0.00025)
    assert shortened.vertices[3][1] == pytest.approx(baseline.vertices[3][1] + 0.00025)
    assert shortened.metadata["total_wire_length_m"] == pytest.approx(
        SHORTENED_CENTERLINE_LENGTH_M
    )


def test_feed_gap_geometry_preserves_arm_length_and_tips() -> None:
    baseline = build_factor_anchor_geometry()
    changed = build_factor_anchor_geometry(feed_gap_m=0.0003)
    assert changed.vertices[0][0] == pytest.approx(-0.00015)
    assert changed.vertices[1][0] == pytest.approx(0.00015)
    assert changed.vertices[2][1] == baseline.vertices[2][1]
    assert changed.vertices[3][1] == baseline.vertices[3][1]
    assert changed.metadata["total_wire_length_m"] == pytest.approx(
        DAY65_DIPOLE_LENGTH_M
    )


def test_radius_change_is_metadata_only() -> None:
    baseline = build_factor_anchor_geometry()
    changed = build_factor_anchor_geometry(wire_radius_m=0.00025)
    assert changed.vertices == baseline.vertices
    assert changed.faces == baseline.faces
    assert changed.metadata["wire_radius_m"] == pytest.approx(0.00025)


def test_residual_bias_is_absolute_and_source_labeled() -> None:
    estimate = residual_bias(
        basis="test",
        nec2_frequency_hz=2.29e9,
        openems_frequency_hz=2.21e9,
    )
    assert estimate.basis == "test"
    assert estimate.residual_hz == 80.0e6
