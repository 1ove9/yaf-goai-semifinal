"""Pure and mock-only gates for the frozen paired-state meander study."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable

import pytest
from pydantic import ValidationError

from yaf_ai.exploration import freeform_wire
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    HardwareSpec,
    PairedMeanderError,
    PairedProposal,
    PairedProposalRejected,
    PairedStateEnvironment,
    SearchCurve,
    StateControl,
    audit_trajectory,
    build_state_geometry,
    find_manual_geometric_witness,
    hardware_hash,
    iter_manual_pairs,
    manual_grid_single_state_evaluations,
    manual_hardware_grid,
    manual_state_grid,
    pair_hash,
    require_same_hardware,
    score_paired_curves,
    score_state_curve,
    select_timing_preflight_pairs,
    state_geometry_hash,
)
from yaf_core.domain.geometry import Geometry


def _hardware(
    *,
    turns: int = 3,
    feed_gap_ppm: int = 20_000,
    terminal_ppm: int = 0,
) -> HardwareSpec:
    return HardwareSpec(
        turn_count=turns,
        feed_gap_ratio_ppm=feed_gap_ppm,
        terminal_ratio_ppm=terminal_ppm,
    )


def _valid_proposal(proposer: str = "test") -> PairedProposal:
    return PairedProposal(
        hardware=_hardware(),
        state_a=StateControl(
            state="A",
            total_wire_length_um=52_005,
            span_ratio_ppm=760_000,
        ),
        state_b=StateControl(
            state="B",
            total_wire_length_um=25_844,
            span_ratio_ppm=760_000,
        ),
        proposer=proposer,
    )


def _invalid_trajectory_proposal() -> PairedProposal:
    return PairedProposal(
        hardware=_hardware(turns=6, terminal_ppm=1_000_000),
        state_a=StateControl(
            state="A",
            total_wire_length_um=50_000,
            span_ratio_ppm=1_000_000,
        ),
        state_b=StateControl(
            state="B",
            total_wire_length_um=22_000,
            span_ratio_ppm=1_000_000,
        ),
        proposer="invalid-test",
    )


def _curve(
    state: str,
    *,
    minimum_index: int = 50,
    depth_db: float = -10.0,
    second_minimum_index: int | None = None,
    solver_name: str = "nec2",
) -> SearchCurve:
    frequency = STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ
    values = [-0.1] * len(frequency)
    values[minimum_index] = depth_db
    if second_minimum_index is not None:
        values[second_minimum_index] = depth_db
    return SearchCurve(
        solver_name=solver_name,
        solver_mode="subprocess",
        frequency_hz=frequency,
        s11_db=tuple(values),
        realized_gain_dbi=tuple(2.0 for _ in frequency),
    )


def test_frozen_frequency_tables_have_101_exact_bins() -> None:
    assert len(STATE_A_FREQUENCIES_HZ) == 101
    assert len(STATE_B_FREQUENCIES_HZ) == 101
    assert STATE_A_FREQUENCIES_HZ[0] == 2.400e9
    assert STATE_A_FREQUENCIES_HZ[-1] == 2.500e9
    assert STATE_B_FREQUENCIES_HZ[0] == 5.725e9
    assert STATE_B_FREQUENCIES_HZ[-1] == 5.875e9


def test_state_scorer_uses_global_minimum_and_lower_frequency_tie() -> None:
    metrics = score_state_curve(
        _curve("A", minimum_index=60, second_minimum_index=40),
        "A",
    )
    assert metrics.selected_index == 40
    assert metrics.selected_frequency_hz == STATE_A_FREQUENCIES_HZ[40]
    assert metrics.selected_s11_db == -10.0
    assert metrics.valid_search
    assert metrics.figure_of_merit == pytest.approx(0.9)
    assert metrics.reflected_power_fraction == pytest.approx(0.1)


@pytest.mark.parametrize(
    ("index", "depth", "expected"),
    (
        (2, -20.0, False),
        (3, -6.0, True),
        (97, -6.0, True),
        (98, -20.0, False),
        (50, -5.999, False),
    ),
)
def test_valid_search_boundaries_are_frozen(
    index: int,
    depth: float,
    expected: bool,
) -> None:
    assert (
        score_state_curve(
            _curve("A", minimum_index=index, depth_db=depth),
            "A",
        ).valid_search
        is expected
    )


def test_paired_score_is_worst_band_fom_plus_validity_bonus() -> None:
    metrics = score_paired_curves(
        _curve("A", depth_db=-10.0),
        _curve("B", depth_db=-7.0),
    )
    expected_b = 1.0 - math.pow(10.0, -0.7)
    assert metrics.base_score == pytest.approx(expected_b)
    assert metrics.valid_pair_search
    assert metrics.search_score == pytest.approx(expected_b + 0.25)
    assert metrics.worst_reflected_power_fraction == pytest.approx(math.pow(10.0, -0.7))


def test_paired_scorer_rejects_openems_and_frequency_table_drift() -> None:
    with pytest.raises(PairedMeanderError, match="NEC2 only"):
        score_state_curve(_curve("A", solver_name="openems"), "A")
    drifted = _curve("A").model_copy(
        update={
            "frequency_hz": (
                STATE_A_FREQUENCIES_HZ[0] + 1.0,
                *STATE_A_FREQUENCIES_HZ[1:],
            )
        }
    )
    with pytest.raises(PairedMeanderError, match="frequency table changed"):
        score_state_curve(drifted, "A")


def test_old_dual_band_scorer_is_not_on_the_paired_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_legacy(*_args: object, **_kwargs: object) -> dict[str, float]:
        raise AssertionError("legacy scorer was called")

    monkeypatch.setattr(
        freeform_wire,
        "evaluate_dual_band_metrics",
        fail_legacy,
    )
    assert score_paired_curves(_curve("A"), _curve("B")).valid_pair_search


def test_centerline_known_answer_uses_only_the_frozen_equation() -> None:
    hardware = HardwareSpec(
        turn_count=4,
        feed_gap_ratio_ppm=40_000,
        terminal_ratio_ppm=500_000,
    )
    state = StateControl(
        state="A",
        total_wire_length_um=61_182,
        span_ratio_ppm=880_000,
    )
    geometry = build_state_geometry(hardware, state)
    gap = 0.040 * 0.040
    span = 0.020 * 0.880
    pitch = (span - gap / 2.0) / 5.0
    horizontal = 4.5 * pitch
    height = (((0.061182 - gap) / 2.0) - horizontal) / 3.5
    assert geometry.metadata["feed_gap_m"] == pytest.approx(gap)
    assert geometry.metadata["minimum_pitch_m"] == pytest.approx(pitch)
    assert geometry.metadata["derived_height_m"] == pytest.approx(height)
    assert geometry.metadata["total_wire_length_m"] == pytest.approx(
        0.061182,
        abs=1e-9,
    )
    right_edge_count = 1 + 4 + 3 + 1
    assert len(geometry.faces) == 1 + 2 * right_edge_count


def test_height_ratio_is_not_a_state_control_field() -> None:
    with pytest.raises(ValidationError):
        StateControl.model_validate(
            {
                "state": "A",
                "total_wire_length_um": 61_182,
                "span_ratio_ppm": 880_000,
                "height_ratio": 0.5,
            }
        )


def test_shared_hardware_hash_is_equal_and_state_hashes_are_distinct() -> None:
    proposal = _valid_proposal()
    first = build_state_geometry(proposal.hardware, proposal.state_a)
    second = build_state_geometry(proposal.hardware, proposal.state_b)
    assert require_same_hardware(proposal.hardware, proposal.hardware) == hardware_hash(
        proposal.hardware
    )
    assert state_geometry_hash(
        proposal.hardware,
        proposal.state_a,
        first,
    ) != state_geometry_hash(
        proposal.hardware,
        proposal.state_b,
        second,
    )
    assert pair_hash(proposal) == pair_hash(proposal.model_copy(deep=True))


def test_shared_hardware_mismatch_is_rejected_before_a_solver() -> None:
    with pytest.raises(PairedProposalRejected, match="identities differ"):
        require_same_hardware(
            _hardware(),
            _hardware(feed_gap_ppm=40_000),
        )


def test_trajectory_audit_records_all_21_points_and_motion_metrics() -> None:
    audit = audit_trajectory(_valid_proposal())
    assert audit.valid
    assert audit.point_count == 21
    assert len(audit.state_geometry_hashes) == 21
    assert audit.minimum_clearance_m is not None
    assert audit.minimum_clearance_m >= 0.0002
    assert audit.minimum_pitch_m is not None
    assert audit.minimum_pitch_m >= 0.0015
    assert audit.minimum_height_m is not None
    assert audit.minimum_height_m > 0.0
    assert audit.maximum_adjacent_node_displacement_m is not None
    assert audit.maximum_adjacent_node_displacement_m > 0.0


def test_invalid_trajectory_is_rejected_without_a_solver_call() -> None:
    assert not audit_trajectory(_invalid_trajectory_proposal()).valid


def test_fixed_manual_grid_counts_and_geometric_witness() -> None:
    assert len(manual_hardware_grid()) == 36
    assert len(manual_state_grid("A")) == 12
    assert len(manual_state_grid("B")) == 12
    assert manual_grid_single_state_evaluations() == 864
    witness = find_manual_geometric_witness()
    assert witness.trajectory.valid
    assert witness.proposal.state_a.state == "A"
    assert witness.proposal.state_b.state == "B"


def test_timing_preflight_selection_is_deterministic_and_has_20_pairs() -> None:
    proposals = tuple(
        proposal for _hardware_index, _pair_index, proposal in iter_manual_pairs()
    )
    assert len(proposals) == 36 * 12 * 12 == 5_184
    first = select_timing_preflight_pairs(proposals)
    second = select_timing_preflight_pairs(reversed(proposals))
    assert len(first) == 20
    assert [pair_hash(item) for item in first] == [pair_hash(item) for item in second]


@pytest.mark.asyncio
async def test_unreleased_anchor_still_allows_nec2_evaluation() -> None:
    calls = 0

    async def solver(
        _geometry: Geometry,
        state: str,
        _frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        nonlocal calls
        calls += 1
        return _curve(state)

    environment = PairedStateEnvironment(
        solver=solver,
        evaluation_budget=2,
        anchor_released=False,
    )
    result = await environment.evaluate(_valid_proposal())
    assert result.metrics.valid_pair_search
    assert calls == 2
    assert environment.evaluations_completed == 1


@pytest.mark.asyncio
async def test_mock_environment_uses_only_the_two_nec2_target_bands() -> None:
    calls: list[tuple[str, tuple[float, ...]]] = []

    async def solver(
        _geometry: Geometry,
        state: str,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        calls.append((state, frequency_hz))
        return _curve(state)

    environment = PairedStateEnvironment(
        solver=solver,
        evaluation_budget=2,
        anchor_released=True,
    )
    result = await environment.evaluate(_valid_proposal())
    assert result.metrics.valid_pair_search
    assert calls == [
        ("A", STATE_A_FREQUENCIES_HZ),
        ("B", STATE_B_FREQUENCIES_HZ),
    ]
    assert result.state_a_curve.solver_name == "nec2"
    assert result.state_b_curve.solver_name == "nec2"
    assert environment.evaluations_completed == 1


@pytest.mark.asyncio
async def test_geometry_rejection_consumes_zero_evaluation_budget() -> None:
    calls = 0

    async def solver(
        _geometry: Geometry,
        state: str,
        _frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        nonlocal calls
        calls += 1
        return _curve(state)

    environment = PairedStateEnvironment(
        solver=solver,
        evaluation_budget=1,
        anchor_released=True,
    )
    with pytest.raises(PairedProposalRejected):
        await environment.evaluate(_invalid_trajectory_proposal())
    assert calls == 0
    assert environment.evaluations_completed == 0
    assert environment.rejections == 1


def test_mock_solver_signature_is_awaitable() -> None:
    async def solver(
        _geometry: Geometry,
        state: str,
        _frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return _curve(state)

    typed: Callable[
        [Geometry, str, tuple[float, ...]],
        Awaitable[SearchCurve],
    ] = solver
    assert typed is solver
