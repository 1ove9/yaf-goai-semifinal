"""Mock-only tests for the frozen Day 3 cross-solver protocol."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from yaf_ai.exploration.baselines import ClassicTemplateBaseline
from yaf_ai.exploration.cross_check import (
    AirVariantDefinition,
    CrossCheckRunSummary,
    SolverCurve,
    WireGridDefinition,
    build_air_variant,
    build_wire_grid,
    evaluate_cross_check,
)
from yaf_ai.exploration.environment import ExplorationConfig
from yaf_ai.exploration.specs import get_spec


def _config() -> ExplorationConfig:
    return ExplorationConfig(
        spec=get_spec("wifi24"),
        evaluation_budget=1,
        seed=101,
    )


def test_air_variant_preserves_metal_area_and_feed_position() -> None:
    source = ClassicTemplateBaseline(_config()).propose().geometry
    variant, definition = build_air_variant(source)

    assert definition.patch_metal_area_m2 == pytest.approx(
        float(source.metadata["length"]) * float(source.metadata["width"])
    )
    assert definition.ground_metal_area_m2 == pytest.approx(
        float(source.metadata["substrate_length"])
        * float(source.metadata["substrate_width"])
    )
    assert variant.metadata["length"] == source.metadata["length"]
    assert variant.metadata["width"] == source.metadata["width"]
    assert variant.metadata["feed_x"] == source.metadata["feed_x"]
    assert variant.metadata["eps_r"] == 1.0
    assert variant.metadata["loss_tangent"] == 0.0


def test_equal_area_wire_grid_preserves_declared_conductor_area() -> None:
    source = ClassicTemplateBaseline(_config()).propose().geometry
    _, definition = build_air_variant(source)
    wires, grid = build_wire_grid(definition)

    represented = (
        2.0
        * 3.141592653589793
        * grid.equal_area_wire_radius_m
        * grid.total_grid_wire_length_m
    )
    assert represented == pytest.approx(grid.represented_metal_area_m2)
    assert wires[0].start_m[:2] == pytest.approx(
        (definition.feed_x_m, definition.feed_y_m)
    )
    assert wires[0].stop_m[:2] == pytest.approx(
        (definition.feed_x_m, definition.feed_y_m)
    )
    assert wires[0].stop_m[2] == pytest.approx(definition.air_gap_m)


@pytest.mark.parametrize(
    ("frequency_difference", "s11_difference", "expected"),
    (
        (0.049, 2.9, "CONFIRMED"),
        (0.051, 2.9, "DIVERGENT"),
        (0.049, 3.1, "DIVERGENT"),
    ),
)
def test_cross_check_threshold_boundaries(
    frequency_difference: float,
    s11_difference: float,
    expected: str,
) -> None:
    decision = evaluate_cross_check(
        1.0e9,
        -10.0,
        1.0e9 * (1.0 + frequency_difference),
        -10.0 - s11_difference,
    )
    assert decision.verdict == expected


def test_divergent_summary_retains_both_curves() -> None:
    air = AirVariantDefinition(
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
    grid = WireGridDefinition(
        grid_intervals=6,
        wire_count=10,
        grid_wire_count=9,
        total_grid_wire_length_m=0.4,
        represented_metal_area_m2=0.0039,
        equal_area_wire_radius_m=0.0002,
        feed_wire_radius_m=0.00008,
    )
    openems = SolverCurve(
        solver_name="openems",
        solver_mode="subprocess",
        frequency_hz=(1.0e9, 1.1e9),
        s11_db=(-10.0, -12.0),
        resonance_frequency_hz=1.1e9,
        resonance_s11_db=-12.0,
        simulation_time_seconds=1.0,
    )
    nec2 = SolverCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=(1.0e9, 1.1e9),
        s11_db=(-3.0, -4.0),
        resonance_frequency_hz=1.0e9,
        resonance_s11_db=-3.0,
        simulation_time_seconds=0.1,
    )
    decision = evaluate_cross_check(1.1e9, -12.0, 1.0e9, -3.0)
    summary = CrossCheckRunSummary(
        run_id="test-crosscheck",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        seed=101,
        config_hash="a" * 64,
        config={},
        solver_mode_counts={"subprocess": 2},
        source_run_id="day2-source",
        source_design_index=0,
        source_geometry_hash="b" * 64,
        spec_name="wifi24",
        air_variant=air,
        wire_grid=grid,
        openems=openems,
        nec2=nec2,
        decision=decision,
    )

    assert summary.decision.verdict == "DIVERGENT"
    assert summary.openems.s11_db == (-10.0, -12.0)
    assert summary.nec2.s11_db == (-3.0, -4.0)
