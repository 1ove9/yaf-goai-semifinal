"""Mock-only checks for the frozen Day 6.5 v2 cross-check sequence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from yaf_ai.exploration.cross_check import SolverCurve
from yaf_ai.exploration.day65_cross_check import (
    Day65V2InstrumentRunSummary,
    build_day65_v2_convergence,
)
from yaf_ai.exploration.day65_selection import SelectedDay65Design


def _selected() -> SelectedDay65Design:
    return SelectedDay65Design(
        rank=1,
        source_run_id="day65-freeform-v2-dual-es-s101",
        source_step_index=20,
        source_geometry_hash="a" * 64,
        source_config_hash="b" * 64,
        source_base_score=0.8,
        source_search_score=1.05,
        source_valid_both_bands=True,
        proposal_parameters={"node_0_x_m": 0.0},
        proposer="es",
        oracle_improvement_fraction=0.2,
    )


def _curve(minimum_index: int, depth: float = -8.0) -> SolverCurve:
    frequencies = tuple(float(value) * 1e9 for value in (
        5.72,
        5.74,
        5.76,
        5.78,
        5.80,
        5.82,
        5.84,
        5.86,
        5.88,
    ))
    values = [-0.2] * len(frequencies)
    values[minimum_index - 1] = depth / 2.0
    values[minimum_index] = depth
    values[minimum_index + 1] = depth / 2.0
    return SolverCurve(
        solver_name="openems",
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=tuple(values),
        resonance_frequency_hz=frequencies[minimum_index],
        resonance_s11_db=depth,
        simulation_time_seconds=10.0,
    )


def _summary(
    refinement: float, minimum_index: int, depth: float = -8.0
) -> Day65V2InstrumentRunSummary:
    timestamp = datetime.now(UTC)
    return Day65V2InstrumentRunSummary(
        run_id=f"day65-freeform-v2-openems-convergence-top1-{refinement:g}x",
        started_at=timestamp,
        finished_at=timestamp,
        seed=101,
        config_hash="c" * 64,
        config={"openems_mesh_refinement": refinement},
        solver_mode_counts={"subprocess": 1},
        selected_design=_selected(),
        curve=_curve(minimum_index, depth),
    )


def test_convergence_records_first_valid_adjacent_pass() -> None:
    document = build_day65_v2_convergence(
        [_summary(1.0, 4), _summary(2.0, 5), _summary(4.0, 5)]
    )
    assert document.levels[1].high_band_shift_from_previous == pytest.approx(
        20.0 / 5.82e3
    )
    assert document.levels[1].comparison_passed
    assert document.first_passing_refinement == 2.0
    assert document.self_convergence_established
    assert document.claim_refinement == 6.0


def test_missing_valid_resonance_never_masquerades_as_zero_shift() -> None:
    document = build_day65_v2_convergence(
        [_summary(1.0, 4, -5.9), _summary(2.0, 4, -5.9)]
    )
    assert document.levels[1].high_band_shift_from_previous is None
    assert not document.levels[1].comparison_passed
    assert not document.self_convergence_established
    assert document.first_passing_refinement is None
