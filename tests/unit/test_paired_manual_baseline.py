"""Mock-only tests for the cached frozen manual baseline and parent freeze."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yaf_ai.exploration.paired_agents import decode_normalized, encode_warm_parent
from yaf_ai.exploration.paired_baseline import (
    MANUAL_BASELINE_RUN_ID,
    MANUAL_PAIR_COUNT,
    MANUAL_SINGLE_STATE_COUNT,
    ManualBaselineSummary,
    assemble_manual_records,
    execute_manual_single_states,
    freeze_manual_warm_parent,
    iter_manual_single_state_work,
    run_manual_baseline,
)
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    PairedProposal,
    SearchCurve,
    StateLabel,
    audit_trajectory,
    hardware_hash,
    iter_manual_pairs,
    manual_hardware_grid,
    manual_state_grid,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRunError,
    freeze_candidate,
)
from yaf_core.domain.geometry import Geometry


def _curve(state: StateLabel, *, depth_db: float = -8.0, mode: str = "subprocess") -> SearchCurve:
    frequencies = STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ
    values = [-0.1] * len(frequencies)
    values[50] = depth_db
    return SearchCurve(
        solver_name="nec2",
        solver_mode=mode,
        frequency_hz=frequencies,
        s11_db=tuple(values),
        realized_gain_dbi=None,
    )


class CountingSolver:
    """Mock solver that records the frozen design-feature identity of each call."""

    def __init__(self, *, mode: str = "subprocess") -> None:
        self.mode = mode
        self.calls: list[tuple[object, ...]] = []

    async def __call__(
        self,
        geometry: Geometry,
        state: StateLabel,
        frequencies: tuple[float, ...],
    ) -> SearchCurve:
        features = geometry.metadata["design_features"]
        assert isinstance(features, dict)
        self.calls.append(
            (
                features["turn_count"],
                features["feed_gap_ratio_ppm"],
                features["terminal_ratio_ppm"],
                state,
                features["total_wire_length_um"],
                features["span_ratio_ppm"],
            )
        )
        expected = STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ
        assert frequencies == expected
        return _curve(state, mode=self.mode)


def _first_pair(*, valid_trajectory: bool) -> tuple[int, int, PairedProposal]:
    for row in iter_manual_pairs():
        if audit_trajectory(row[2]).valid is valid_trajectory:
            return row
    raise AssertionError("manual grid did not contain the requested trajectory class")


def _pair_cache(proposal: PairedProposal) -> dict[tuple[str, StateLabel, int, int], SearchCurve]:
    digest = hardware_hash(proposal.hardware)
    return {
        (
            digest,
            "A",
            proposal.state_a.total_wire_length_um,
            proposal.state_a.span_ratio_ppm,
        ): _curve("A"),
        (
            digest,
            "B",
            proposal.state_b.total_wire_length_um,
            proposal.state_b.span_ratio_ppm,
        ): _curve("B"),
    }


def test_864_key_order_matches_frozen_hardware_a_then_b_grids() -> None:
    rows = iter_manual_single_state_work()
    assert len(rows) == MANUAL_SINGLE_STATE_COUNT == 864
    assert len({row.key.identity() for row in rows}) == 864
    hardware = manual_hardware_grid()
    state_a = manual_state_grid("A")
    state_b = manual_state_grid("B")
    expected: list[tuple[object, ...]] = []
    for hardware_index, hardware_row in enumerate(hardware):
        digest = hardware_hash(hardware_row)
        for state_index, state in enumerate((*state_a, *state_b)):
            expected.append(
                (
                    hardware_index,
                    state_index % 12,
                    digest,
                    state.state,
                    state.total_wire_length_um,
                    state.span_ratio_ppm,
                )
            )
    actual = [
        (
            row.hardware_grid_index,
            row.state_grid_index,
            row.key.hardware_hash,
            row.key.state_label,
            row.key.total_wire_length_um,
            row.key.span_ratio_ppm,
        )
        for row in rows
    ]
    assert actual == expected


@pytest.mark.asyncio
async def test_single_state_cache_calls_mock_solver_once_per_valid_key(
    tmp_path: Path,
) -> None:
    solver = CountingSolver()
    result = await execute_manual_single_states(
        solver=solver,
        log_path=tmp_path / "log.jsonl",
    )
    assert result.succeeded + result.rejected == MANUAL_SINGLE_STATE_COUNT
    assert len(solver.calls) == result.succeeded
    assert len(set(solver.calls)) == len(solver.calls)
    assert len(result.cache) == result.succeeded
    assert result.solver_mode_counts == {"subprocess": result.succeeded}
    event_types = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert event_types.count("single_state_evaluation") == result.succeeded
    assert event_types.count("single_state_rejected") == result.rejected


def test_12_by_12_assembly_uses_cache_only_and_excludes_missing_curves() -> None:
    row = _first_pair(valid_trajectory=True)
    cache = _pair_cache(row[2])
    complete = assemble_manual_records(cache, (row,))
    assert complete.scored_pairs == 1
    assert complete.curve_incomplete_pairs == 0
    assert complete.records[0].hardware_grid_index == row[0]
    assert complete.records[0].pair_grid_index == row[1]
    assert complete.records[0].proposer == "manual-physics-baseline"

    cache.pop(next(key for key in cache if key[1] == "B"))
    missing = assemble_manual_records(cache, (row,))
    assert missing.scored_pairs == 0
    assert missing.curve_incomplete_pairs == 1
    assert missing.records == ()


def test_trajectory_invalid_pair_is_absent_from_parent_pool() -> None:
    row = _first_pair(valid_trajectory=False)
    assembled = assemble_manual_records(_pair_cache(row[2]), (row,))
    assert assembled.trajectory_invalid_pairs == 1
    assert assembled.scored_pairs == 0
    assert assembled.records == ()


def _records(count: int = 3) -> list[PairedEvaluationRecord]:
    rows: list[PairedEvaluationRecord] = []
    for manual_row in iter_manual_pairs():
        if not audit_trajectory(manual_row[2]).valid:
            continue
        assembled = assemble_manual_records(_pair_cache(manual_row[2]), (manual_row,))
        rows.append(assembled.records[0])
        if len(rows) == count:
            return rows
    raise AssertionError("not enough legal manual records")


def _metrics_record(
    record: PairedEvaluationRecord,
    *,
    base_score: float,
    search_score: float,
    valid: bool,
    hardware_digest: str | None = None,
    hardware_grid_index: int | None = None,
    pair_grid_index: int | None = None,
) -> PairedEvaluationRecord:
    metrics = record.evaluation.metrics.model_copy(
        update={
            "base_score": base_score,
            "search_score": search_score,
            "valid_pair_search": valid,
        }
    )
    evaluation = record.evaluation.model_copy(
        update={
            "hardware_hash": (
                record.evaluation.hardware_hash
                if hardware_digest is None
                else hardware_digest
            ),
            "metrics": metrics,
        }
    )
    return record.model_copy(
        update={
            "evaluation": evaluation,
            "hardware_grid_index": (
                record.hardware_grid_index
                if hardware_grid_index is None
                else hardware_grid_index
            ),
            "pair_grid_index": (
                record.pair_grid_index if pair_grid_index is None else pair_grid_index
            ),
        }
    )


def test_parent_freeze_prefers_valid_pool_and_uses_frozen_tie_breaks() -> None:
    first, second, third = _records()
    invalid_high = _metrics_record(
        first, base_score=0.99, search_score=0.99, valid=False
    )
    valid_low = _metrics_record(second, base_score=0.60, search_score=0.85, valid=True)
    valid_high = _metrics_record(third, base_score=0.70, search_score=0.95, valid=True)
    selected = freeze_manual_warm_parent((invalid_high, valid_low, valid_high))
    assert selected.pair_hash == valid_high.evaluation.pair_hash
    assert selected.positive_eligible
    assert selected.valid_pair_search

    tie_a = _metrics_record(
        first,
        base_score=0.5,
        search_score=0.5,
        valid=False,
        hardware_digest="a" * 64,
        hardware_grid_index=2,
        pair_grid_index=9,
    )
    tie_b = _metrics_record(
        second,
        base_score=0.5,
        search_score=0.5,
        valid=False,
        hardware_digest="a" * 64,
        hardware_grid_index=2,
        pair_grid_index=8,
    )
    diagnostic = freeze_manual_warm_parent((tie_a, tie_b))
    assert diagnostic.pair_hash == tie_b.evaluation.pair_hash
    assert not diagnostic.positive_eligible


def test_manual_parent_encoding_round_trips_every_quantized_field() -> None:
    parent = freeze_manual_warm_parent(_records(1))
    encoded = encode_warm_parent(parent.proposal)
    assert tuple(float(value) for value in encoded) == parent.encoded_warm_parent
    rebuilt = decode_normalized(parent.encoded_warm_parent, "es")
    assert rebuilt.hardware == parent.proposal.hardware
    assert rebuilt.state_a == parent.proposal.state_a
    assert rebuilt.state_b == parent.proposal.state_b


def test_manual_baseline_is_excluded_from_agent_candidate_pool() -> None:
    record = _records(1)[0]
    baseline = record.model_copy(update={"run_id": MANUAL_BASELINE_RUN_ID})
    with pytest.raises(PairedRunError, match="non-agent exclusion"):
        freeze_candidate((baseline,))


@pytest.mark.asyncio
async def test_non_subprocess_curve_terminates_whole_baseline_without_parent(
    tmp_path: Path,
) -> None:
    summary = await run_manual_baseline(tmp_path, CountingSolver(mode="fallback_analytical"))
    assert summary.result_status == "execution_failed"
    assert summary.warm_parent_pair_hash is None
    assert summary.verdict_ceiling == "insufficient_evidence"
    assert "requires real NEC2 subprocess" in (summary.failure_message or "")
    assert not (
        tmp_path
        / "artifacts"
        / "analysis"
        / "semifinal-paired-manual-baseline"
        / "warm_parent.json"
    ).exists()
    persisted = ManualBaselineSummary.model_validate_json(
        (tmp_path / "runs" / MANUAL_BASELINE_RUN_ID / "summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted == summary


def test_frozen_preflight_and_anchor_archives_retain_exact_sha256() -> None:
    expected = {
        "semifinal-paired-budget-preflight": (
            "48f5e5cf05e7a8f93e89f0ddb72a92531debb07ea322a0fcfb7553b3d346092b",
            "b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138",
        ),
        "semifinal-wifi58-meander-renderer-anchor-r1-combined": (
            "937bd9d53a992a7bfce54d886652291fbac49c366f8fd617d4681f5ff4258b89",
            "61d012118b489634f9e04c4c5a02ada6532edbf3e9088f68806376b6b07f68c7",
        ),
        "semifinal-wifi58-meander-renderer-anchor-r2-combined": (
            "8d8387a9859417d6e9f62c07a385ba4d6a89e204e579d6c0359ddeb3b241de2c",
            "5c0987c439f21147e187cbc630870b57aaea3e6736569d05d28b232fe2dd7871",
        ),
        "semifinal-wifi58-meander-renderer-anchor-r3-combined": (
            "0e9da50876fa679870160ba9349a8391c18d7917355d7cef50177899bb967a9f",
            "d5ac661dc0251d0e7dcecf7a88d967a2c510e568e3338a45c5e84399254f67a9",
        ),
        "semifinal-wifi58-rod-renderer-anchor-r1-combined": (
            "39414489ba7b34f8b94526f03c657741ce879b2d521a4061df58b93b802c699f",
            "152710277aa5f8b4586185a0a00fd77d2d0d1ebf9907d3b130fe0e0972a06d0e",
        ),
    }
    for run_id, (log_hash, summary_hash) in expected.items():
        run_directory = Path("artifacts/runs") / run_id
        assert hashlib.sha256((run_directory / "log.jsonl").read_bytes()).hexdigest() == log_hash
        assert (
            hashlib.sha256((run_directory / "summary.json").read_bytes()).hexdigest()
            == summary_hash
        )


def test_manual_pair_constant_is_exact() -> None:
    assert MANUAL_PAIR_COUNT == 36 * 12 * 12 == 5_184
    assert datetime.now(UTC).tzinfo is UTC
