"""Tests for exact-support Stage-B analysis and reporting."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yaf_ai.analysis import paired_feasible_stage_b as stage_b
from yaf_ai.analysis.paired_feasible_stage_b import (
    AGENTS,
    L_REQUIRED,
    SEEDS,
    TURNS,
    StageBCellRow,
    StageBRecordRef,
    build_stage_b_appendix,
    expected_run_id,
    render_stage_b_report,
    summarize_turn,
    write_stage_b_outputs,
)
from yaf_ai.exploration.paired_feasible_batch import (
    RANDOM_AGENT,
    StageBFrozenInputs,
    build_stage_b_proposer,
)
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    SearchCurve,
)
from yaf_ai.exploration.paired_runner import PairedEvaluationRecord, _evaluation


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _record(
    agent: str,
    seed: int,
    turn: int,
    *,
    index: int = 0,
    valid: bool = True,
    reflected: float = 0.3,
    base_score: float = 0.7,
    hardware_hash: str = "h",
    pair_hash: str | None = None,
) -> StageBRecordRef:
    return StageBRecordRef(
        run_id=expected_run_id(agent, seed),  # type: ignore[arg-type]
        agent=agent,  # type: ignore[arg-type]
        seed=seed,
        turn=turn,
        step_index=index,
        proposal_index=index,
        hardware_hash=_digest(hardware_hash),
        pair_hash=_digest(pair_hash or f"pair-{index}"),
        valid_pair_search=valid,
        base_score=base_score,
        worst_reflected_power_fraction=reflected,
    )


def _cell(agent: str, seed: int, records: tuple[StageBRecordRef, ...]) -> StageBCellRow:
    turns = tuple(summarize_turn(turn, records) for turn in TURNS)
    return StageBCellRow(
        agent=agent,  # type: ignore[arg-type]
        seed=seed,
        run_id=expected_run_id(agent, seed),  # type: ignore[arg-type]
        execution_status="completed",
        source_status="completed",
        accepted_count=600,
        rejected_count=0,
        proposal_attempts=600,
        solver_mode_counts={"subprocess": 1200},
        mapping_invariant_failures=0,
        turns=turns,
        log_sha256="a" * 64,
        summary_sha256="b" * 64,
    )


def _matrix_records(*, cross_seed: bool = False) -> tuple[StageBRecordRef, ...]:
    records: list[StageBRecordRef] = []
    for agent in AGENTS:
        for seed in SEEDS:
            for turn in TURNS:
                for offset in range(150):
                    passed = cross_seed and agent == "es" and turn == 5 and seed != 505 and offset == 0
                    records.append(
                        _record(
                            agent,
                            seed,
                            turn,
                            index=turn * 10_000 + seed * 100 + offset,
                            reflected=(L_REQUIRED if passed else 0.3),
                            pair_hash=f"{agent}-{seed}-{turn}-{offset:03d}",
                        )
                    )
    return tuple(records)


def _rows(records: tuple[StageBRecordRef, ...]) -> tuple[StageBCellRow, ...]:
    return tuple(
        _cell(
            agent,
            seed,
            tuple(record for record in records if record.agent == agent and record.seed == seed),
        )
        for agent in AGENTS
        for seed in SEEDS
    )


def test_complete_cross_seed_endpoint_uses_es_four_of_five() -> None:
    records = _matrix_records(cross_seed=True)
    appendix = build_stage_b_appendix(_rows(records), records)
    assert appendix.study_status == "complete"
    assert appendix.scientific_endpoint == "turn_stratified_cross_seed_gate_crossing"
    assert appendix.selected_hypothesis is not None
    assert appendix.selected_hypothesis.agent == "es"
    assert appendix.selected_hypothesis.turn == 5
    counts = {
        (item.agent, item.turn): item.pass_count
        for item in appendix.turn_seed_counts or ()
    }
    assert counts[("es", 5)] == 4


def test_random_crossing_cannot_replace_es_primary_endpoint() -> None:
    records = list(_matrix_records())
    first = next(index for index, record in enumerate(records) if record.agent == "random")
    records[first] = records[first].model_copy(
        update={"worst_reflected_power_fraction": L_REQUIRED}
    )
    frozen = tuple(records)
    appendix = build_stage_b_appendix(_rows(frozen), frozen)
    assert appendix.scientific_endpoint == (
        "no_gate_crossing_observed_under_frozen_stratified_study"
    )
    assert appendix.selected_hypothesis is not None
    assert appendix.selected_hypothesis.agent == "es"


def test_incomplete_matrix_has_null_aggregates() -> None:
    records = _matrix_records()
    rows = list(_rows(records))
    failed = rows[3]
    rows[3] = failed.model_copy(
        update={
            "execution_status": "execution_failed",
            "source_status": "proposal_sequence_exhausted",
            "exception_type": "IllegalTerminal",
            "exception_message": "source status is not completed",
        }
    )
    rows[3] = StageBCellRow.model_validate(rows[3].model_dump())

    appendix = build_stage_b_appendix(
        tuple(rows),
        records,
        matrix_exception_type="IllegalTerminal",
        matrix_exception_message="cell 4 did not reach completed",
    )
    assert appendix.study_status == "study_incomplete"
    assert appendix.scientific_endpoint is None
    assert appendix.turn_seed_counts is None
    assert appendix.selected_hypothesis is None


def test_within_cell_ranking_uses_full_frozen_tiebreak_key() -> None:
    records = (
        _record("es", 101, 3, index=9, reflected=0.2, hardware_hash="b", pair_hash="a"),
        _record("es", 101, 3, index=8, reflected=0.2, hardware_hash="a", pair_hash="z"),
        _record("es", 101, 3, index=7, reflected=0.2, hardware_hash="a", pair_hash="c"),
    )
    row = summarize_turn(3, records)
    assert row.best_valid == min(
        records,
        key=lambda record: (
            record.worst_reflected_power_fraction,
            record.hardware_hash,
            record.pair_hash,
            record.step_index,
            record.proposal_index,
        ),
    )


def test_duplicate_pair_hash_counts_once_but_preserves_accepted_count() -> None:
    records = (
        _record("es", 101, 3, index=0, pair_hash="same"),
        _record("es", 101, 3, index=1, pair_hash="same"),
        _record("es", 101, 3, index=2, pair_hash="different"),
    )
    row = summarize_turn(3, records)
    assert row.accepted_count == 3
    assert row.unique_candidate_count == 2
    assert row.valid_count == 2


def test_duplicate_pair_hash_with_conflicting_metrics_is_rejected() -> None:
    first = _record("es", 101, 3, index=0, pair_hash="same")
    second = _record(
        "es",
        101,
        3,
        index=1,
        pair_hash="same",
        reflected=0.25,
    )
    with pytest.raises(ValueError, match="inconsistent diagnostics"):
        summarize_turn(3, (first, second))


def _curve(frequencies: tuple[float, ...]) -> SearchCurve:
    values = [-0.1] * len(frequencies)
    values[len(values) // 2] = -8.0
    return SearchCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=tuple(values),
        realized_gain_dbi=None,
    )


def test_replay_rejects_well_formed_proposal_from_the_wrong_seed() -> None:
    wrong = build_stage_b_proposer(RANDOM_AGENT, 202).propose()
    event = PairedEvaluationRecord(
        run_id=expected_run_id("random", 101),
        step_index=0,
        proposal_index=0,
        timestamp=datetime.now(UTC),
        proposer=RANDOM_AGENT,
        proposal=wrong,
        evaluation=_evaluation(
            wrong,
            _curve(STATE_A_FREQUENCIES_HZ),
            _curve(STATE_B_FREQUENCIES_HZ),
        ),
    )
    with pytest.raises(Exception, match="replay|proposal|pending"):
        stage_b._replay_diagnostics((event,), RANDOM_AGENT, 101)


def test_record_ref_rejects_metric_only_and_trajectory_only_tampering() -> None:
    proposal = build_stage_b_proposer(RANDOM_AGENT, 101).propose()
    evaluation = _evaluation(
        proposal,
        _curve(STATE_A_FREQUENCIES_HZ),
        _curve(STATE_B_FREQUENCIES_HZ),
    )
    record = PairedEvaluationRecord(
        run_id=expected_run_id("random", 101),
        step_index=0,
        proposal_index=0,
        timestamp=datetime.now(UTC),
        proposer=RANDOM_AGENT,
        proposal=proposal,
        evaluation=evaluation,
    )
    tampered_metrics = evaluation.metrics.model_copy(
        update={"base_score": evaluation.metrics.base_score + 0.001}
    )
    with pytest.raises(ValueError, match="do not recompute"):
        stage_b._record_ref(
            record.model_copy(
                update={
                    "evaluation": evaluation.model_copy(
                        update={"metrics": tampered_metrics}
                    )
                }
            ),
            RANDOM_AGENT,
            101,
        )

    tampered_trajectory = evaluation.trajectory.model_copy(
        update={"point_count": evaluation.trajectory.point_count - 1}
    )
    with pytest.raises(ValueError, match="do not recompute"):
        stage_b._record_ref(
            record.model_copy(
                update={
                    "evaluation": evaluation.model_copy(
                        update={"trajectory": tampered_trajectory}
                    )
                }
            ),
            RANDOM_AGENT,
            101,
        )


def test_record_rejects_non_sha256_source_hashes() -> None:
    payload = _record("es", 101, 3).model_dump()
    payload["pair_hash"] = "not-a-hash"
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        StageBRecordRef.model_validate(payload)


def test_loader_treats_tampered_first_log_as_failed_prefix(tmp_path: Path) -> None:
    run_id = expected_run_id("random", 101)
    run_directory = tmp_path / "runs" / run_id
    run_directory.mkdir(parents=True)
    (run_directory / "log.jsonl").write_bytes(b"{tampered}\n")
    inputs = StageBFrozenInputs(
        execution_commit="a" * 40,
        implementation_commit="b" * 40,
        stage_a_evidence_commit="c" * 40,
        stage_a_summary_sha256="d" * 64,
        stage_a_report_sha256="e" * 64,
    )
    appendix = stage_b.load_stage_b_evidence(tmp_path, inputs)
    assert appendix.study_status == "study_incomplete"
    assert appendix.rows[0].execution_status == "execution_failed"
    assert all(
        row.execution_status == "not_run_after_matrix_abort"
        for row in appendix.rows[1:]
    )
    assert appendix.turn_seed_counts is None
    assert appendix.selected_hypothesis is None


def test_no_valid_diagnostic_uses_negative_base_score_then_hashes() -> None:
    records = (
        _record("es", 101, 6, index=2, valid=False, base_score=0.8, hardware_hash="b"),
        _record("es", 101, 6, index=1, valid=False, base_score=0.8, hardware_hash="a"),
        _record("es", 101, 6, index=0, valid=False, base_score=0.7, hardware_hash="0"),
    )
    row = summarize_turn(6, records)
    assert row.diagnostic_top == min(
        records,
        key=lambda record: (
            -record.base_score,
            record.hardware_hash,
            record.pair_hash,
            record.step_index,
            record.proposal_index,
        ),
    )


def test_completed_cell_requires_exact_quota_and_subprocess_counts() -> None:
    records = _matrix_records()
    cell = _rows(records)[0]
    payload = cell.model_dump()
    payload["solver_mode_counts"] = {"subprocess": 1198}
    with pytest.raises(ValueError, match="sole legal terminal"):
        StageBCellRow.model_validate(payload)


def test_report_and_outputs_disclose_every_cell(tmp_path: Path) -> None:
    records = _matrix_records(cross_seed=True)
    appendix = build_stage_b_appendix(_rows(records), records)
    report = render_stage_b_report(appendix)
    assert report.count("| random |") == 5
    assert report.count("| es |") == 5
    assert "not independent-solver confirmation" in report
    write_stage_b_outputs(tmp_path, appendix)
    assert b"\r" not in (tmp_path / "appendix.json").read_bytes()
    assert b"\r" not in (tmp_path / "report.md").read_bytes()

def test_seed_local_endpoint_and_selection_are_deterministic() -> None:
    records = list(_matrix_records())
    index = next(
        index
        for index, record in enumerate(records)
        if record.agent == "es" and record.seed == 303 and record.turn == 4
    )
    records[index] = records[index].model_copy(
        update={"worst_reflected_power_fraction": L_REQUIRED}
    )
    frozen = tuple(records)
    appendix = build_stage_b_appendix(_rows(frozen), frozen)
    assert appendix.scientific_endpoint == "turn_stratified_seed_local_gate_crossing"
    assert appendix.selected_hypothesis == records[index]


def test_no_valid_es_pool_uses_global_diagnostic_key() -> None:
    records = tuple(
        record.model_copy(
            update={
                "valid_pair_search": False,
                "base_score": 0.8 if record.agent == "es" else record.base_score,
            }
        )
        for record in _matrix_records()
    )
    appendix = build_stage_b_appendix(_rows(records), records)
    assert appendix.scientific_endpoint == (
        "no_gate_crossing_observed_under_frozen_stratified_study"
    )
    assert appendix.selected_hypothesis is not None
    assert appendix.selected_hypothesis.agent == "es"
    expected = min(
        (record for record in records if record.agent == "es"),
        key=lambda record: (
            -record.base_score,
            record.hardware_hash,
            record.pair_hash,
            record.turn,
            record.seed,
            record.step_index,
            record.proposal_index,
        ),
    )
    assert appendix.selected_hypothesis == expected


def test_complete_appendix_rejects_tampered_aggregate() -> None:
    records = _matrix_records(cross_seed=True)
    appendix = build_stage_b_appendix(_rows(records), records)
    payload = appendix.model_dump()
    payload["scientific_endpoint"] = (
        "no_gate_crossing_observed_under_frozen_stratified_study"
    )
    with pytest.raises(ValueError, match="endpoint does not recompute"):
        type(appendix).model_validate(payload)
