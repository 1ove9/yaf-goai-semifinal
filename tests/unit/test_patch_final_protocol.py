"""Frozen resource and extrapolation rules for the final patch study."""

from __future__ import annotations

import pytest

from yaf_ai.exploration.cross_check import AirVariantDefinition
from yaf_ai.exploration.cross_check import build_wire_grid as build_v1_wire_grid
from yaf_ai.exploration.cross_check_v2 import build_wire_grid as build_v2_wire_grid
from yaf_ai.exploration.patch_final_protocol import (
    MAX_SINGLE_RUN_SECONDS,
    dense_complex_matrix_bytes,
    grid_estimate_for_pearson,
    grid_segment_count,
    power_law_grid_estimate,
    predict_cubic_runtime_seconds,
    resources_feasible,
    wire_reference_gap_for_pearson,
)


def test_dynamic_grid_six_is_byte_equivalent_to_day3_v1_mapping() -> None:
    definition = AirVariantDefinition(
        patch_length_m=0.027433149426814046,
        patch_width_m=0.03793719346702928,
        patch_metal_area_m2=0.0010407366972149678,
        ground_length_m=0.04793442089991226,
        ground_width_m=0.06628832042275558,
        ground_metal_area_m2=0.003177492251892616,
        air_gap_m=0.0016,
        feed_x_m=-0.006913319650378899,
        feed_y_m=0.0,
        original_eps_r=4.4,
    )
    v1_wires, v1_grid = build_v1_wire_grid(definition)
    v2_wires, v2_grid, _spacing = build_v2_wire_grid(definition, 6)
    assert v2_wires == v1_wires
    assert v2_grid == v1_grid


def test_grid_segment_count_and_cubic_prediction() -> None:
    assert grid_segment_count(24) == 2401
    assert grid_segment_count(44) == 7921
    predicted = predict_cubic_runtime_seconds(
        baseline_grid_intervals=24,
        baseline_actual_seconds=295.125,
        target_grid_intervals=44,
    )
    ratio = 7921 / 2401
    assert predicted == pytest.approx(295.125 * ratio**3)
    assert dense_complex_matrix_bytes(7921) == 7921**2 * 16


@pytest.mark.parametrize(
    ("seconds", "matrix_bytes", "expected"),
    [
        (MAX_SINGLE_RUN_SECONDS, 800, (True, True, True)),
        (MAX_SINGLE_RUN_SECONDS + 1e-6, 800, (False, True, False)),
        (MAX_SINGLE_RUN_SECONDS, 801, (True, False, False)),
    ],
)
def test_resource_gate_inclusive_boundaries(
    seconds: float, matrix_bytes: int, expected: tuple[bool, bool, bool]
) -> None:
    assert resources_feasible(
        predicted_seconds=seconds,
        predicted_matrix_bytes=matrix_bytes,
        available_memory_bytes=1000,
    ) == expected


def test_power_law_is_refit_when_new_point_arrives() -> None:
    original = power_law_grid_estimate(
        (6, 12, 24),
        (0.3111142542064606, 0.1444489419748679, 0.08889394255660296),
    )
    updated = power_law_grid_estimate(
        (6, 12, 24, 32),
        (0.3111142542064606, 0.1444489419748679, 0.08889394255660296, 0.06),
    )
    assert original == 44
    assert updated is not None
    assert updated != original


def test_nonmonotonic_gap_has_no_power_law_claim() -> None:
    assert power_law_grid_estimate((6, 12, 24), (0.3, 0.1, 0.2)) is None


def test_wire_reference_maps_pearson_target_to_patch_grid() -> None:
    target_gap = wire_reference_gap_for_pearson()
    assert target_gap is not None
    assert 0.011811 < target_gap < 0.04478
    estimate = grid_estimate_for_pearson(
        (6, 12, 24),
        (0.3111142542064606, 0.1444489419748679, 0.08889394255660296),
    )
    assert estimate is not None
    assert estimate > 44
