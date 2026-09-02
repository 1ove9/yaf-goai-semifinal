"""Support-equivalence tests for feasibility-preserving coordinates."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from yaf_ai.exploration.paired_feasible_coordinates import (
    FEASIBLE_VECTOR_DIMENSIONS,
    MAPPING_VERSION,
    ZERO_TERMINAL_CUTOFF,
    FeasibleCoordinateInvariantError,
    _minimum_positive_terminal,
    _state_a_minimum,
    _state_b_minimum,
    decode_feasible_coordinates,
    encode_feasible_coordinates,
    exact_nominal_failure_reason,
    scalar_trajectory_is_legal,
)
from yaf_ai.exploration.paired_meander import (
    MANUAL_TURN_COUNTS,
    HardwareSpec,
    PairedProposal,
    StateControl,
    audit_trajectory,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _proposal(
    turn: int,
    terminal: int,
    *,
    a_length: int = 100_000,
    a_span: int = 760_000,
    b_length: int = 45_000,
    b_span: int = 760_000,
    proposer: str = "boundary",
) -> PairedProposal:
    return PairedProposal(
        hardware=HardwareSpec(
            turn_count=turn,
            feed_gap_ratio_ppm=20_000,
            terminal_ratio_ppm=terminal,
        ),
        state_a=StateControl(
            state="A", total_wire_length_um=a_length, span_ratio_ppm=a_span
        ),
        state_b=StateControl(
            state="B", total_wire_length_um=b_length, span_ratio_ppm=b_span
        ),
        proposer=proposer,
    )


def _round_trip(proposal: PairedProposal) -> None:
    vector = encode_feasible_coordinates(proposal)
    assert len(vector) == FEASIBLE_VECTOR_DIMENSIONS
    assert decode_feasible_coordinates(
        vector,
        turn_count=proposal.hardware.turn_count,
        proposer=proposal.proposer,
    ) == proposal


def _exact_reason(proposal: PairedProposal) -> str | None:
    return exact_nominal_failure_reason(
        turn_count=proposal.hardware.turn_count,
        feed_gap_ratio_ppm=proposal.hardware.feed_gap_ratio_ppm,
        terminal_ratio_ppm=proposal.hardware.terminal_ratio_ppm,
        state_a_length_um=proposal.state_a.total_wire_length_um,
        state_a_span_ppm=proposal.state_a.span_ratio_ppm,
        state_b_length_um=proposal.state_b.total_wire_length_um,
        state_b_span_ppm=proposal.state_b.span_ratio_ppm,
    )


def test_zero_cutoff_and_six_field_order_are_frozen() -> None:
    assert MAPPING_VERSION == "conditional-exact-feasible-turn-v2"
    assert ZERO_TERMINAL_CUTOFF.numerator == 1
    assert ZERO_TERMINAL_CUTOFF.denominator == 16
    assert FEASIBLE_VECTOR_DIMENSIONS == 6

    decoded = decode_feasible_coordinates(
        (0.0, 0.0, 1.0, 0.0, 1.0, 0.0),
        turn_count=3,
        proposer="order",
    )
    assert decoded.hardware.feed_gap_ratio_ppm == 20_000
    assert decoded.hardware.terminal_ratio_ppm == 0
    assert decoded.state_a.total_wire_length_um == 100_000
    assert decoded.state_a.span_ratio_ppm == 760_000
    assert decoded.state_b.total_wire_length_um == 45_000
    assert decoded.state_b.span_ratio_ppm == 760_000


@pytest.mark.parametrize("turn", MANUAL_TURN_COUNTS)
def test_turn_boundaries_cover_zero_minimum_positive_and_maximum_terminal(
    turn: int,
) -> None:
    terminal_minimum = _minimum_positive_terminal(turn, 20_000, 760_000, 760_000)
    rejected = _proposal(turn, terminal_minimum - 1)
    assert _exact_reason(rejected) == (
        "exact_nominal_constraint_failed:terminal:trajectory_index=00"
    )
    for terminal in (0, terminal_minimum, terminal_minimum + 1, 1_000_000):
        proposal = _proposal(turn, terminal)
        assert audit_trajectory(proposal).valid
        _round_trip(proposal)


@pytest.mark.parametrize("turn", MANUAL_TURN_COUNTS)
def test_conditional_lower_upper_and_interior_lengths_round_trip(turn: int) -> None:
    lower = decode_feasible_coordinates(
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        turn_count=turn,
        proposer="length-boundary",
    )
    upper = decode_feasible_coordinates(
        (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        turn_count=turn,
        proposer="length-boundary",
    )
    interior = decode_feasible_coordinates(
        (0.5, 0.5, 0.5, 0.5, 0.5, 0.5),
        turn_count=turn,
        proposer="length-boundary",
    )
    for proposal in (lower, upper, interior):
        assert audit_trajectory(proposal).valid
        _round_trip(proposal)
    if turn == 6:
        narrow = decode_feasible_coordinates(
            (1.0, 1.0, 1.0, 1.0, 0.0, 1.0),
            turn_count=turn,
            proposer="turn-6-narrow-boundary",
        )
        assert 44_400 <= narrow.state_b.total_wire_length_um <= 45_000
        _round_trip(narrow)


@pytest.mark.parametrize("turn", MANUAL_TURN_COUNTS)
def test_dynamic_b_then_a_length_boundaries_are_explicit(turn: int) -> None:
    feed_gap = 20_000
    terminal = 0
    a_span = 760_000
    b_span = 760_000
    b_minimum = _state_b_minimum(
        turn,
        feed_gap,
        terminal,
        a_span,
        b_span,
    )
    b_below = _proposal(
        turn,
        terminal,
        a_length=100_000,
        a_span=a_span,
        b_length=b_minimum - 1,
        b_span=b_span,
    )
    assert _exact_reason(b_below) is not None
    for b_length in (b_minimum, b_minimum + 1, 45_000):
        proposal = _proposal(
            turn,
            terminal,
            a_length=100_000,
            a_span=a_span,
            b_length=b_length,
            b_span=b_span,
        )
        assert _exact_reason(proposal) is None
        _round_trip(proposal)

    a_minimum = _state_a_minimum(
        turn,
        feed_gap,
        terminal,
        a_span,
        45_000,
        b_span,
    )
    assert a_minimum == 50_000
    with pytest.raises(ValueError, match="state A total_wire_length_um"):
        _proposal(
            turn,
            terminal,
            a_length=a_minimum - 1,
            a_span=a_span,
            b_length=45_000,
            b_span=b_span,
        )
    for a_length in (a_minimum, a_minimum + 1, 100_000):
        proposal = _proposal(
            turn,
            terminal,
            a_length=a_length,
            a_span=a_span,
            b_length=45_000,
            b_span=b_span,
        )
        assert _exact_reason(proposal) is None
        _round_trip(proposal)


def test_property_vectors_are_scalar_and_full_audit_legal() -> None:
    for turn in MANUAL_TURN_COUNTS:
        rng = np.random.default_rng(np.random.SeedSequence([101, 0, turn, 1]))
        for vector in rng.random((250, FEASIBLE_VECTOR_DIMENSIONS)):
            proposal = decode_feasible_coordinates(
                vector.tolist(), turn_count=turn, proposer="property"
            )
            assert scalar_trajectory_is_legal(
                turn_count=turn,
                feed_gap_ratio_ppm=proposal.hardware.feed_gap_ratio_ppm,
                terminal_ratio_ppm=proposal.hardware.terminal_ratio_ppm,
                state_a_length_um=proposal.state_a.total_wire_length_um,
                state_a_span_ppm=proposal.state_a.span_ratio_ppm,
                state_b_length_um=proposal.state_b.total_wire_length_um,
                state_b_span_ppm=proposal.state_b.span_ratio_ppm,
            )
            assert audit_trajectory(proposal).valid


def test_all_r2_accepted_proposals_round_trip_byte_for_byte() -> None:
    root = _repo_root()
    exact_count = 0
    excluded_count = 0
    for log_path in sorted(
        (root / "artifacts/runs").glob("semifinal-paired-r2-es-warm-s*/log.jsonl")
    ):
        for line in log_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            if payload.get("event_type") != "paired_evaluation":
                continue
            proposal = PairedProposal.model_validate(payload["proposal"])
            reason = _exact_reason(proposal)
            if reason is None:
                _round_trip(proposal)
                exact_count += 1
            else:
                excluded_count += 1
    assert (exact_count, excluded_count) == (2_000, 0)


def test_frozen_warm_source_exact_support_round_trip_counts_are_fixed() -> None:
    root = _repo_root()
    path = root / "artifacts/runs/semifinal-paired-es-warm-s101/log.jsonl"
    exact_count = 0
    excluded_count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if payload.get("event_type") != "paired_evaluation":
            continue
        proposal = PairedProposal.model_validate(payload["proposal"])
        if _exact_reason(proposal) is None:
            _round_trip(proposal)
            exact_count += 1
        else:
            excluded_count += 1
    assert (exact_count, excluded_count) == (300, 0)


@pytest.mark.parametrize(
    ("proposal", "expected_reason"),
    (
        (
            PairedProposal(
                hardware=HardwareSpec(
                    turn_count=5,
                    feed_gap_ratio_ppm=27_302,
                    terminal_ratio_ppm=77_650,
                ),
                state_a=StateControl(
                    state="A", total_wire_length_um=100_000, span_ratio_ppm=800_000
                ),
                state_b=StateControl(
                    state="B", total_wire_length_um=45_000, span_ratio_ppm=800_000
                ),
                proposer="tolerance-witness",
            ),
            "exact_nominal_constraint_failed:terminal:trajectory_index=00",
        ),
        (
            PairedProposal(
                hardware=HardwareSpec(
                    turn_count=3,
                    feed_gap_ratio_ppm=27_933,
                    terminal_ratio_ppm=449_231,
                ),
                state_a=StateControl(
                    state="A", total_wire_length_um=50_000, span_ratio_ppm=951_144
                ),
                state_b=StateControl(
                    state="B", total_wire_length_um=34_961, span_ratio_ppm=951_144
                ),
                proposer="tolerance-witness",
            ),
            "exact_nominal_constraint_failed:height_min:trajectory_index=20",
        ),
    ),
)
def test_binary64_tolerance_witnesses_are_disclosed_v2_exclusions(
    proposal: PairedProposal,
    expected_reason: str,
) -> None:
    assert audit_trajectory(proposal).valid
    reason = _exact_reason(proposal)
    assert reason == expected_reason
    with pytest.raises(FeasibleCoordinateInvariantError, match=expected_reason):
        encode_feasible_coordinates(proposal)


def test_exact_failure_rule_order_covers_unreachable_guard_branches() -> None:
    assert exact_nominal_failure_reason(
        turn_count=6,
        feed_gap_ratio_ppm=60_000,
        terminal_ratio_ppm=1_000_000,
        state_a_length_um=100_000,
        state_a_span_ppm=500_000,
        state_b_length_um=45_000,
        state_b_span_ppm=500_000,
    ) == "exact_nominal_constraint_failed:pitch:trajectory_index=00"
    assert exact_nominal_failure_reason(
        turn_count=3,
        feed_gap_ratio_ppm=20_000,
        terminal_ratio_ppm=0,
        state_a_length_um=500_000,
        state_a_span_ppm=760_000,
        state_b_length_um=500_000,
        state_b_span_ppm=760_000,
    ) == "exact_nominal_constraint_failed:height_max:trajectory_index=00"


def test_invalid_inputs_and_illegal_proposals_fail_closed() -> None:
    with pytest.raises(FeasibleCoordinateInvariantError, match="six dimensions"):
        decode_feasible_coordinates((0.0,) * 5, turn_count=3, proposer="bad")
    with pytest.raises(FeasibleCoordinateInvariantError, match="finite"):
        decode_feasible_coordinates(
            (0.0, 0.0, 0.0, 0.0, 0.0, float("nan")),
            turn_count=3,
            proposer="bad",
        )
    illegal = _proposal(6, 1_000_000, a_length=50_000, b_length=22_000)
    assert not audit_trajectory(illegal).valid
    with pytest.raises(FeasibleCoordinateInvariantError, match="illegal proposal"):
        encode_feasible_coordinates(illegal)


def test_decoder_source_has_no_solver_or_result_dependency() -> None:
    source_path = _repo_root() / "yaf_ai/exploration/paired_feasible_coordinates.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    prohibited = ("solver", "openems", "s11", "score", "frequency", "candidate")
    assert all(token not in source.lower() for token in prohibited)
    assert all("solver" not in name.lower() for name in imported)


def test_frozen_science_files_remain_unmodified() -> None:
    root = _repo_root()
    expected = {
        "yaf_ai/exploration/paired_runner.py": "d2ece9096be6daa86de6b281bb64a8b1150c782e",
        "yaf_ai/exploration/paired_solver.py": "96efa9fe3e755fbca9b31315d96a330bef7291b9",
        "yaf_ai/exploration/paired_meander.py": "98fd67154d5f6a512fdf46b99da1fc273ba8eced",
        "yaf_ai/exploration/paired_agents.py": "0b8b8046611bca0fd2e0c0649277e5594f439f99",
        "yaf_ai/exploration/day65_batch.py": "5944f5c2f9c892aa0a6860b2ef443f914f6baecc",
    }
    for relative, blob in expected.items():
        actual = subprocess.run(
            ["git", "hash-object", str(root / relative)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert actual == blob
