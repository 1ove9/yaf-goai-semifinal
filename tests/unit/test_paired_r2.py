"""Regression tests for the bounded post-freeze R2 study."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from pydantic import ValidationError

import scripts.paired_r2_batch as r2_cli
import yaf_ai.exploration.paired_r2_batch as r2_batch
import yaf_ai.exploration.paired_r2_report as r2_report
from yaf_ai.exploration.day65_batch import ES_INITIAL_SIGMA, reflect_normalized
from yaf_ai.exploration.paired_agents import decode_normalized, encode_warm_parent
from yaf_ai.exploration.paired_candidates import CandidateFreezeDocument
from yaf_ai.exploration.paired_meander import (
    PairedEvaluation,
    PairedProposal,
    PairedSolver,
    SearchCurve,
    StateLabel,
    audit_trajectory,
    pair_hash,
)
from yaf_ai.exploration.paired_r2_agents import R2ParentReturnES
from yaf_ai.exploration.paired_r2_batch import (
    BUDGET_SOURCE_COMMIT,
    EFFECT_DOCUMENT_PATH,
    FROZEN_SCIENCE_BLOBS,
    R2_BUDGET_CONFIG_HASH,
    R2_BUDGET_SUMMARY_SHA256,
    R2_EFFECT_COMMIT,
    R2_EFFECT_DOCUMENT_SHA256,
    R2_EVALUATION_BUDGET,
    R2_L_REQUIRED,
    R2_PARENT_PAIR_HASH,
    R2_PARENT_PROPOSAL_INDEX,
    R2_PARENT_SEARCH_SCORE,
    R2_PARENT_SOURCE_LOG_SHA256,
    R2_PREREGISTRATION_COMMIT,
    R2_RUN_ID_PREFIX,
    R2_SEEDS,
    R2CellResult,
    R2MatrixError,
    R2PairedRunConfig,
    _validate_budget,
    _validate_parent_evidence,
    _validate_source_manifest,
)
from yaf_ai.exploration.paired_r2_report import (
    BoundaryDiagnostics,
    BoundaryFieldStats,
    R2Appendix,
    R2BaselineDiagnostics,
    R2RecordRef,
    R2SeedRow,
    TurnDistribution,
)
from yaf_ai.exploration.paired_runner import (
    PairedRunConfig,
    PairedRunSummary,
    _config_hash,
    _load_paired_events,
    _replay_proposer,
    run_paired_adaptive,
)
from yaf_core.domain.geometry import Geometry


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parent() -> tuple[PairedProposal, PairedEvaluation]:
    document = CandidateFreezeDocument.model_validate_json(
        (_repo_root() / EFFECT_DOCUMENT_PATH).read_bytes()
    )
    candidate = next(
        item for item in document.candidates if item.pair_hash == R2_PARENT_PAIR_HASH
    )
    log_path = (
        _repo_root()
        / "artifacts/runs/semifinal-paired-es-warm-s101/log.jsonl"
    )
    row = next(
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if json.loads(line).get("step_index") == 213
    )
    from yaf_ai.exploration.paired_runner import PairedEvaluationRecord  # noqa: PLC0415

    record = PairedEvaluationRecord.model_validate(row)
    return candidate.proposal, record.evaluation


def _config_payload(seed: int = 101) -> dict[str, object]:
    return {
        "run_id": f"{R2_RUN_ID_PREFIX}{seed}",
        "agent": "es-r2",
        "seed": seed,
        "evaluation_budget": R2_EVALUATION_BUDGET,
        "anchor_released": False,
        "openems_cross_check_authorized": False,
        "preregistration_commit": R2_PREREGISTRATION_COMMIT,
        "execution_commit": "f" * 40,
        "budget_source_summary_sha256": R2_BUDGET_SUMMARY_SHA256,
        "budget_source_config_hash": R2_BUDGET_CONFIG_HASH,
        "r2_parent_pair_hash": R2_PARENT_PAIR_HASH,
        "r2_parent_hardware_hash": (
            "b6f72349504b6994a10ff9d32ffb7059424073fb25bc2900860f7e1348b9340c"
        ),
        "r2_parent_state_a_geometry_hash": (
            "4d8c585c7e4112d1d8aad9d8c33b55642549008cec6649075a75ffa4a4b15b55"
        ),
        "r2_parent_state_b_geometry_hash": (
            "84566f8b6ab538d6ff1ae730b2ecd74f445fc127f877f8edb1a53530e509c33e"
        ),
        "r2_parent_source_run_id": "semifinal-paired-es-warm-s101",
        "r2_parent_source_step": 213,
        "r2_parent_proposal_index": 658,
        "r2_parent_source_commit": (
            "a19684b5449774db82b21907cc11c7874287f838"
        ),
        "r2_parent_source_log_sha256": R2_PARENT_SOURCE_LOG_SHA256,
        "r2_parent_source_summary_sha256": (
            "52cd3ad16c3db5b2f3d98ab2bf394e69d4f6af0381d595d88edd3de3f98e25b7"
        ),
        "r2_parent_source_config_hash": (
            "7ed5e6758e8ffd554fa2bcd9e323611f46e0e099a5b2fdd9c74f6ec4401e9cde"
        ),
        "r2_parent_search_score": R2_PARENT_SEARCH_SCORE,
        "r2_l_manual": 0.21548949210811824,
        "r2_l_required": R2_L_REQUIRED,
        "r2_effect_source_commit": R2_EFFECT_COMMIT,
        "r2_effect_document_sha256": R2_EFFECT_DOCUMENT_SHA256,
        "r2_budget_source_commit": BUDGET_SOURCE_COMMIT,
    }


def test_r2_config_contains_all_final_c_triple_prime_provenance() -> None:
    hashes: set[str] = set()
    for seed in R2_SEEDS:
        config = R2PairedRunConfig.model_validate(_config_payload(seed))
        dumped = config.model_dump(mode="json")
        assert dumped["r2_parent_proposal_index"] == R2_PARENT_PROPOSAL_INDEX
        assert dumped["r2_parent_source_log_sha256"] == R2_PARENT_SOURCE_LOG_SHA256
        assert dumped["r2_parent_search_score"] == R2_PARENT_SEARCH_SCORE
        assert dumped["r2_effect_source_commit"] == R2_EFFECT_COMMIT
        assert dumped["r2_effect_document_sha256"] == R2_EFFECT_DOCUMENT_SHA256
        assert dumped["r2_budget_source_commit"] == BUDGET_SOURCE_COMMIT
        assert dumped["manual_baseline_commit"] is None
        assert all(
            value is None
            for key, value in dumped.items()
            if key.startswith("warm_parent_")
        )
        hashes.add(_config_hash(config))
    assert len(hashes) == 5
    assert repr(R2_L_REQUIRED) == "0.19394054289730642"


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("agent", "es-warm"),
        ("evaluation_budget", 300),
        ("seed", 999),
        ("run_id", "wrong"),
        ("anchor_released", True),
        ("openems_cross_check_authorized", True),
        ("max_consecutive_rejections", 99),
        ("max_total_proposal_attempts", 5999),
        ("budget_source_summary_sha256", "0" * 64),
        ("budget_source_config_hash", "0" * 64),
        ("preregistration_commit", "short"),
        ("preregistration_commit", "0" * 40),
        ("execution_commit", "short"),
        ("execution_commit", None),
        ("execution_commit", "g" * 40),
        ("manual_baseline_commit", "0" * 40),
        ("warm_parent_run_id", "wrong"),
        ("warm_parent_pair_hash", "0" * 64),
        ("warm_parent_document_sha256", "0" * 64),
        ("warm_parent_hardware_hash", "0" * 64),
        ("warm_parent_state_a_geometry_hash", "0" * 64),
        ("warm_parent_state_b_geometry_hash", "0" * 64),
        ("warm_parent_step_index", 0),
        ("warm_parent_hardware_grid_index", 0),
        ("warm_parent_pair_grid_index", 0),
        ("warm_parent_search_score", 0.0),
        ("r2_parent_pair_hash", "0" * 64),
        ("r2_parent_hardware_hash", "0" * 64),
        ("r2_parent_state_a_geometry_hash", "0" * 64),
        ("r2_parent_state_b_geometry_hash", "0" * 64),
        ("r2_parent_source_run_id", "wrong"),
        ("r2_parent_source_step", 212),
        ("r2_parent_source_log_sha256", "0" * 64),
        ("r2_parent_source_summary_sha256", "0" * 64),
        ("r2_parent_source_config_hash", "0" * 64),
        ("r2_parent_source_commit", "0" * 40),
        ("r2_parent_proposal_index", 657),
        ("r2_parent_search_score", 0.7945832225323137),
        ("r2_l_manual", 0.2),
        ("r2_l_required", 0.2),
        ("r2_effect_source_commit", "0" * 40),
        ("r2_effect_document_sha256", "0" * 64),
        ("r2_budget_source_commit", "0" * 40),
    ),
)
def test_r2_config_rejects_single_field_drift(
    field: str,
    bad_value: object,
) -> None:
    payload = R2PairedRunConfig.model_validate(_config_payload()).model_dump(mode="json")
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        R2PairedRunConfig.model_validate(payload)


def test_r2_config_rejects_missing_parent_log_digest() -> None:
    payload = _config_payload()
    del payload["r2_parent_source_log_sha256"]
    with pytest.raises(ValidationError):
        R2PairedRunConfig.model_validate(payload)


def test_base_config_rejects_es_r2_and_r2_rejects_warm_fields() -> None:
    with pytest.raises(ValidationError):
        PairedRunConfig.model_validate(_config_payload())
    payload = _config_payload()
    payload["warm_parent_pair_hash"] = R2_PARENT_PAIR_HASH
    with pytest.raises(ValidationError, match="only es-warm"):
        R2PairedRunConfig.model_validate(payload)
    payload = _config_payload()
    payload["agent"] = "es-warm"
    payload["r2_parent_pair_hash"] = R2_PARENT_PAIR_HASH
    with pytest.raises(ValidationError):
        R2PairedRunConfig.model_validate(payload)


def _lower_score_evaluation(
    proposal: PairedProposal,
    template: PairedEvaluation,
) -> PairedEvaluation:
    metrics = template.metrics.model_copy(
        update={"search_score": R2_PARENT_SEARCH_SCORE - 1.0}
    )
    return template.model_copy(
        update={"pair_hash": pair_hash(proposal), "metrics": metrics}
    )


def _run_nonimprovements(
    proposer: R2ParentReturnES,
    template: PairedEvaluation,
    count: int,
) -> None:
    accepted = 0
    while accepted < count:
        proposal = proposer.propose()
        if not audit_trajectory(proposal).valid:
            proposer.reject(proposal)
            continue
        proposer.observe(_lower_score_evaluation(proposal, template))
        accepted += 1


def test_r2_parent_return_restart_is_immediate_repeatable_and_replayable() -> None:
    parent, template = _parent()
    first = R2ParentReturnES(
        101,
        return_parent=parent,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )
    assert first.return_parent_pair_hash == R2_PARENT_PAIR_HASH
    _run_nonimprovements(first, template, 74)
    assert first.restart_count == 0
    _run_nonimprovements(first, template, 1)
    assert first.restart_count == 1
    assert first.parent_pair_hash == R2_PARENT_PAIR_HASH
    assert first.restart_pending is False
    assert first.sigma == ES_INITIAL_SIGMA
    assert first.consecutive_non_improvements == 0

    second = R2ParentReturnES(
        101,
        return_parent=parent,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )
    _run_nonimprovements(second, template, 75)
    first_after_restart = first.propose()
    second_after_restart = second.propose()
    assert first_after_restart == second_after_restart
    first.reject(first_after_restart)
    _run_nonimprovements(first, template, 75)
    assert first.restart_count == 2


def test_r2_parent_return_restart_consumes_the_next_normal_draw_not_uniform() -> None:
    parent, template = _parent()
    proposer = R2ParentReturnES(
        303,
        return_parent=parent,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )
    _run_nonimprovements(proposer, template, 75)
    assert proposer.restart_count == 1

    state = copy.deepcopy(proposer._rng.bit_generator.state)  # noqa: SLF001
    normal_rng = np.random.default_rng()
    normal_rng.bit_generator.state = copy.deepcopy(state)
    expected_vector = reflect_normalized(
        encode_warm_parent(parent)
        + normal_rng.normal(0.0, ES_INITIAL_SIGMA, 7)
    )
    expected = decode_normalized(expected_vector.tolist(), "es")

    uniform_rng = np.random.default_rng()
    uniform_rng.bit_generator.state = copy.deepcopy(state)
    wrong_uniform = decode_normalized(uniform_rng.random(7).tolist(), "es")

    actual = proposer.propose()
    assert actual == expected
    assert actual != wrong_uniform
    assert actual.proposer == "es"


def test_r2_rejection_does_not_advance_restart_adaptation() -> None:
    parent, _template = _parent()
    proposer = R2ParentReturnES(
        202,
        return_parent=parent,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )
    proposal = proposer.propose()
    proposer.reject(proposal)
    assert proposer.restart_count == 0
    assert proposer.consecutive_non_improvements == 0
    assert proposer.sigma == ES_INITIAL_SIGMA


class _R2InterruptibleSolver:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def __call__(
        self,
        _geometry: Geometry,
        _state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("injected R2 interruption")
        values = (-0.1,) * len(frequency_hz)
        return SearchCurve(
            solver_name="nec2",
            solver_mode="subprocess",
            frequency_hz=frequency_hz,
            s11_db=values,
        )


def _normalized_rows(path: Path) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row.pop("timestamp")
    return cast(list[dict[str, object]], rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on_call", (149, 151, 153))
async def test_r2_persisted_resume_matches_uninterrupted_across_restart_boundary(
    tmp_path: Path,
    fail_on_call: int,
) -> None:
    config = R2PairedRunConfig.model_validate(_config_payload(101))
    parent, _template = _parent()
    full_root = tmp_path / f"full-{fail_on_call}"
    resumed_root = tmp_path / f"resumed-{fail_on_call}"

    full_proposer = R2ParentReturnES(
        101,
        return_parent=parent,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )
    full_summary = await run_paired_adaptive(
        config=config,
        proposer=full_proposer,
        solver=cast(PairedSolver, _R2InterruptibleSolver()),
        runs_root=full_root,
    )
    assert full_summary.status == "completed"

    with pytest.raises(RuntimeError, match="R2 interruption"):
        await run_paired_adaptive(
            config=config,
            proposer=R2ParentReturnES(
                101,
                return_parent=parent,
                return_parent_search_score=R2_PARENT_SEARCH_SCORE,
            ),
            solver=cast(
                PairedSolver,
                _R2InterruptibleSolver(fail_on_call=fail_on_call),
            ),
            runs_root=resumed_root,
        )
    resumed_proposer = R2ParentReturnES(
        101,
        return_parent=parent,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )
    resumed_summary = await run_paired_adaptive(
        config=config,
        proposer=resumed_proposer,
        solver=cast(PairedSolver, _R2InterruptibleSolver()),
        runs_root=resumed_root,
    )
    assert resumed_summary.status == "completed"

    full_log = full_root / config.run_id / "log.jsonl"
    resumed_log = resumed_root / config.run_id / "log.jsonl"
    assert _normalized_rows(resumed_log) == _normalized_rows(full_log)
    replayed = R2ParentReturnES(
        101,
        return_parent=parent,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )
    _replay_proposer(replayed, _load_paired_events(resumed_log))
    assert replayed.restart_count == resumed_proposer.restart_count
    assert replayed.restart_count == full_proposer.restart_count


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_seed", (303, 505))
async def test_run_r2_matrix_reports_live_replay_mismatch_after_legal_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_seed: int,
) -> None:
    parent, _template = _parent()
    fake_inputs = object()

    class FakeProposer:
        restart_count = 0

    async def fake_runner(**kwargs: object) -> PairedRunSummary:
        config = cast(R2PairedRunConfig, kwargs["config"])
        summary = _terminal_summary(config.seed)
        summary_path = tmp_path / "runs" / config.run_id / "summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary.model_dump_json(), encoding="utf-8")
        return summary

    async def unused_solver(
        _geometry: Geometry,
        _state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return SearchCurve(
            solver_name="nec2",
            solver_mode="subprocess",
            frequency_hz=frequency_hz,
            s11_db=(-0.1,) * len(frequency_hz),
        )

    monkeypatch.setattr(r2_batch, "load_r2_frozen_inputs", lambda _root: fake_inputs)
    monkeypatch.setattr(
        r2_batch,
        "build_r2_config",
        lambda seed, _inputs: R2PairedRunConfig.model_validate(_config_payload(seed)),
    )
    monkeypatch.setattr(
        r2_batch,
        "build_r2_proposer",
        lambda _seed, _inputs: FakeProposer(),
    )
    monkeypatch.setattr(r2_batch, "run_paired_adaptive", fake_runner)
    monkeypatch.setattr(
        r2_batch,
        "_replayed_restart_count",
        lambda _path, seed, _inputs: 1 if seed == failed_seed else 0,
    )

    with pytest.raises(R2MatrixError) as captured:
        await r2_batch.run_r2_matrix(
            tmp_path,
            solver_factory=lambda: cast(PairedSolver, unused_solver),
        )
    error = captured.value
    assert error.failed_seed == failed_seed
    assert error.failed_seed_started is True
    assert tuple(result.summary.seed for result in error.confirmed_results) == (
        R2_SEEDS[: R2_SEEDS.index(failed_seed)]
    )
    assert (
        tmp_path
        / "runs"
        / f"{R2_RUN_ID_PREFIX}{failed_seed}"
        / "summary.json"
    ).is_file()
    assert parent is not None


@pytest.mark.asyncio
async def test_run_r2_matrix_presolver_gate_failure_constructs_no_solver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def fail_gate(_root: Path) -> object:
        raise RuntimeError("injected evidence gate failure")

    def solver_factory() -> PairedSolver:
        nonlocal constructed
        constructed = True
        return cast(PairedSolver, _R2InterruptibleSolver())

    monkeypatch.setattr(r2_batch, "load_r2_frozen_inputs", fail_gate)
    with pytest.raises(R2MatrixError) as captured:
        await r2_batch.run_r2_matrix(tmp_path, solver_factory=solver_factory)
    assert captured.value.failed_seed is None
    assert captured.value.failed_seed_started is False
    assert captured.value.confirmed_results == ()
    assert constructed is False


def test_real_archived_r2_sources_pass_individual_pre_solver_gates() -> None:
    root = _repo_root()
    _validate_source_manifest(root)
    preflight = _validate_budget(root)
    candidate, record = _validate_parent_evidence(root)
    assert preflight.raw_budget == 907
    assert candidate.proposal == record.proposal
    assert candidate.search_score == R2_PARENT_SEARCH_SCORE


def _zero_field(denominator: int) -> BoundaryFieldStats:
    return BoundaryFieldStats(
        lower_count=0,
        upper_count=0,
        either_count=0,
        fraction=None if denominator == 0 else 0.0,
    )


def _boundary(pool: str, denominator: int) -> BoundaryDiagnostics:
    return BoundaryDiagnostics.model_validate(
        {
            "pool": pool,
            "denominator": denominator,
            "feed_gap_ratio_ppm": _zero_field(denominator),
            "terminal_ratio_ppm": _zero_field(denominator),
            "state_a_total_wire_length_um": _zero_field(denominator),
            "state_a_span_ratio_ppm": _zero_field(denominator),
            "state_b_total_wire_length_um": _zero_field(denominator),
            "state_b_span_ratio_ppm": _zero_field(denominator),
        }
    )


def _turns(total: int) -> TurnDistribution:
    return TurnDistribution(
        count_3=total,
        count_4=0,
        count_5=0,
        count_6=0,
        total=total,
    )


def _seed_row(seed: int, passed: bool) -> R2SeedRow:
    valid_count = 1 if passed else 0
    effective = valid_count if valid_count else 400
    record = R2RecordRef(
        run_id=f"{R2_RUN_ID_PREFIX}{seed}",
        seed=seed,
        step_index=0,
        proposal_index=0,
        pair_hash="1" * 64 if passed else "2" * 64,
        hardware_hash="3" * 64,
        state_a_geometry_hash="4" * 64,
        state_b_geometry_hash="5" * 64,
        valid_pair_search=passed,
        base_score=1.0,
        search_score=1.0,
        worst_reflected_power_fraction=R2_L_REQUIRED if passed else 0.9,
    )
    return R2SeedRow(
        seed=seed,
        run_id=f"{R2_RUN_ID_PREFIX}{seed}",
        execution_status="completed",
        source_run_status="completed",
        accepted_count=400,
        valid_count=valid_count,
        rejected_count=0,
        proposal_attempts=400,
        solver_mode_counts={"subprocess": 800},
        best_valid_l=R2_L_REQUIRED if passed else None,
        best_valid_record=record if passed else None,
        best_gate_crossing_record=record if passed else None,
        diagnostic_top=None if passed else record,
        pass_flag=passed,
        restart_count=1,
        terminal_consecutive_rejections=0,
        accepted_turns=_turns(400),
        effective_turns=_turns(effective),
        rejection_reasons={},
        boundary=_boundary("valid" if passed else "accepted", effective),
        log_sha256="6" * 64,
        summary_sha256="7" * 64,
    )


def _baseline() -> R2BaselineDiagnostics:
    record = R2RecordRef(
        run_id="semifinal-paired-es-warm-s101",
        seed=101,
        step_index=213,
        proposal_index=658,
        pair_hash=R2_PARENT_PAIR_HASH,
        hardware_hash="3" * 64,
        state_a_geometry_hash="4" * 64,
        state_b_geometry_hash="5" * 64,
        valid_pair_search=True,
        base_score=1.0,
        search_score=R2_PARENT_SEARCH_SCORE,
        worst_reflected_power_fraction=0.20541677746768625,
    )
    return R2BaselineDiagnostics(
        source_run_id="semifinal-paired-es-warm-s101",
        source_log_sha256=R2_PARENT_SOURCE_LOG_SHA256,
        source_summary_sha256=(
            "52cd3ad16c3db5b2f3d98ab2bf394e69d4f6af0381d595d88edd3de3f98e25b7"
        ),
        accepted_count=300,
        valid_count=48,
        rejected_count=536,
        proposal_attempts=836,
        best_valid_l=0.20541677746768625,
        best_valid_record=record,
        accepted_turns=_turns(300),
        effective_turns=_turns(48),
        rejection_reasons={"fixture rejection": 536},
        boundary=_boundary("valid", 48),
    )


def _terminal_summary(seed: int) -> PairedRunSummary:
    config = R2PairedRunConfig.model_validate(_config_payload(seed))
    timestamp = datetime(2026, 8, 30, tzinfo=UTC)
    return PairedRunSummary(
        run_id=config.run_id,
        started_at=timestamp,
        finished_at=timestamp,
        seed=seed,
        config_hash=_config_hash(config),
        config=config.model_dump(mode="json"),
        steps_completed=400,
        evaluation_budget=400,
        solver_mode_counts={"subprocess": 800},
        rejected_proposals=0,
        proposal_attempts=400,
        status="completed",
        termination_reason="accepted paired-evaluation budget completed",
    )


def _cell(seed: int) -> R2CellResult:
    return R2CellResult(summary=_terminal_summary(seed), restart_count=1)


def _failed_row(seed: int, source_status: str = "completed") -> R2SeedRow:
    payload = _seed_row(seed, False).model_dump(mode="json")
    payload.update(
        {
            "execution_status": "execution_failed",
            "source_run_status": source_status,
            "pass_flag": None,
            "restart_count": None,
            "terminal_consecutive_rejections": None,
            "best_gate_crossing_record": None,
            "exception_type": "PairedBatchError",
            "exception_message": "injected replay mismatch",
        }
    )
    return R2SeedRow.model_validate(payload)


def _not_run_row(seed: int) -> R2SeedRow:
    return R2SeedRow(
        seed=seed,
        run_id=f"{R2_RUN_ID_PREFIX}{seed}",
        execution_status="not_run_after_matrix_abort",
        accepted_count=0,
        valid_count=0,
        rejected_count=0,
        proposal_attempts=0,
        solver_mode_counts={},
        pass_flag=None,
        accepted_turns=_turns(0),
        effective_turns=_turns(0),
        rejection_reasons={},
        boundary=_boundary("none", 0),
    )


@pytest.mark.parametrize(
    ("failed_seed", "confirmed_seeds"),
    (
        (None, (101,)),
        (202, ()),
        (303, (101,)),
        (202, (101, 202)),
        (303, (101, 101)),
        (999, ()),
    ),
)
def test_r2_matrix_error_rejects_nonprefix_state(
    failed_seed: int | None,
    confirmed_seeds: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError):
        R2MatrixError(
            RuntimeError("injected"),
            failed_seed=failed_seed,
            failed_seed_started=False,
            confirmed_results=tuple(_cell(seed) for seed in confirmed_seeds),
        )


@pytest.mark.parametrize("failed_seed", R2_SEEDS)
def test_r2_matrix_error_accepts_exact_confirmed_prefix(failed_seed: int) -> None:
    failed_index = R2_SEEDS.index(failed_seed)
    error = R2MatrixError(
        RuntimeError("injected"),
        failed_seed=failed_seed,
        failed_seed_started=True,
        confirmed_results=tuple(_cell(seed) for seed in R2_SEEDS[:failed_index]),
    )
    assert error.failed_seed == failed_seed
    assert error.failed_seed_started is True


def test_r2_matrix_error_rejects_started_presolver_failure() -> None:
    with pytest.raises(ValueError):
        R2MatrixError(
            RuntimeError("injected"),
            failed_seed=None,
            failed_seed_started=True,
            confirmed_results=(),
        )


def test_r2_matrix_error_normalizes_empty_exception_message() -> None:
    error = R2MatrixError(
        RuntimeError(),
        failed_seed=None,
        failed_seed_started=False,
        confirmed_results=(),
    )
    assert error.cause_type == "RuntimeError"
    assert error.cause_message == "<no message>"


def test_r2_cell_result_rejects_changed_summary_identity() -> None:
    summary = _terminal_summary(101).model_copy(update={"run_id": "wrong"})
    with pytest.raises(ValidationError):
        R2CellResult(summary=summary, restart_count=0)


@pytest.mark.parametrize("failed_seed", (303, 505))
def test_r2_appendix_structured_replay_failure_never_releases_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_seed: int,
) -> None:
    failed_index = R2_SEEDS.index(failed_seed)
    confirmed = tuple(_cell(seed) for seed in R2_SEEDS[:failed_index])
    for result in confirmed:
        path = (
            tmp_path
            / "runs"
            / result.summary.run_id
            / "summary.json"
        )
        path.parent.mkdir(parents=True)
        path.write_text(result.summary.model_dump_json(), encoding="utf-8")

    monkeypatch.setattr(r2_report, "_baseline_diagnostics", lambda _root: _baseline())
    monkeypatch.setattr(
        r2_report,
        "_terminal_row",
        lambda _root, seed, _summary, _restart: _seed_row(seed, False),
    )

    def fake_nonterminal(
        _root: Path,
        seed: int,
        status: str,
        _error_type: str | None,
        _error_message: str | None,
    ) -> R2SeedRow:
        return _failed_row(seed) if status == "execution_failed" else _not_run_row(seed)

    monkeypatch.setattr(r2_report, "_nonterminal_row", fake_nonterminal)
    error = R2MatrixError(
        RuntimeError("live/replay count mismatch"),
        failed_seed=failed_seed,
        failed_seed_started=True,
        confirmed_results=confirmed,
    )
    appendix = r2_report.build_r2_appendix(tmp_path, matrix_error=error)
    expected_statuses = tuple(
        "completed"
        if index < failed_index
        else "execution_failed"
        if index == failed_index
        else "not_run_after_matrix_abort"
        for index in range(len(R2_SEEDS))
    )
    assert tuple(row.execution_status for row in appendix.rows) == expected_statuses
    assert appendix.rows[failed_index].source_run_status == "completed"
    assert appendix.study_status == "study_incomplete"
    assert appendix.pass_count is None
    assert appendix.valid_pair_seed_count is None
    assert appendix.cross_seed_gate_pass is None
    assert appendix.scientific_endpoint is None


def test_r2_appendix_presolver_failure_marks_all_seeds_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(r2_report, "_baseline_diagnostics", lambda _root: _baseline())
    monkeypatch.setattr(
        r2_report,
        "_nonterminal_row",
        lambda _root, seed, _status, _type, _message: _not_run_row(seed),
    )
    error = R2MatrixError(
        RuntimeError("evidence gate failed"),
        failed_seed=None,
        failed_seed_started=False,
        confirmed_results=(),
    )
    appendix = r2_report.build_r2_appendix(tmp_path, matrix_error=error)
    assert all(
        row.execution_status == "not_run_after_matrix_abort"
        for row in appendix.rows
    )
    assert appendix.scientific_endpoint is None


def test_r2_appendix_unstarted_middle_seed_and_stale_evidence_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    confirmed = tuple(_cell(seed) for seed in (101, 202))
    for result in confirmed:
        summary_path = (
            tmp_path / "runs" / result.summary.run_id / "summary.json"
        )
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text(result.summary.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(r2_report, "_baseline_diagnostics", lambda _root: _baseline())
    monkeypatch.setattr(
        r2_report,
        "_terminal_row",
        lambda _root, seed, _summary, _restart: _seed_row(seed, False),
    )
    monkeypatch.setattr(
        r2_report,
        "_nonterminal_row",
        lambda _root, seed, _status, _type, _message: _not_run_row(seed),
    )
    error = R2MatrixError(
        RuntimeError("proposer construction failed"),
        failed_seed=303,
        failed_seed_started=False,
        confirmed_results=confirmed,
    )
    appendix = r2_report.build_r2_appendix(tmp_path, matrix_error=error)
    assert tuple(row.execution_status for row in appendix.rows) == (
        "completed",
        "completed",
        "not_run_after_matrix_abort",
        "not_run_after_matrix_abort",
        "not_run_after_matrix_abort",
    )
    assert appendix.scientific_endpoint is None

    stale_path = tmp_path / "runs" / f"{R2_RUN_ID_PREFIX}303" / "state.json"
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unstarted R2 seed"):
        r2_report.build_r2_appendix(tmp_path, matrix_error=error)


def test_r2_appendix_requires_all_restart_counts_without_matrix_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(r2_report, "_baseline_diagnostics", lambda _root: _baseline())
    with pytest.raises(ValueError, match="exact five-seed"):
        r2_report.build_r2_appendix(tmp_path, restart_counts={101: 0})


def test_r2_valid_seed_count_can_exceed_gate_pass_count() -> None:
    rows = [_seed_row(seed, False) for seed in R2_SEEDS]
    payload = _seed_row(101, True).model_dump(mode="json")
    best = dict(payload["best_valid_record"])
    best["worst_reflected_power_fraction"] = math.nextafter(
        R2_L_REQUIRED,
        math.inf,
    )
    payload.update(
        {
            "best_valid_l": best["worst_reflected_power_fraction"],
            "best_valid_record": best,
            "best_gate_crossing_record": None,
            "pass_flag": False,
        }
    )
    rows[0] = R2SeedRow.model_validate(payload)
    appendix = R2Appendix(
        study_status="complete",
        rows=tuple(rows),
        baseline_diagnostics=_baseline(),
        pass_count=0,
        valid_pair_seed_count=1,
        cross_seed_gate_pass=False,
        scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
    )
    assert appendix.valid_pair_seed_count == 1
    assert appendix.pass_count == 0


def test_r2_gate_witness_is_independent_of_best_valid_record() -> None:
    payload = _seed_row(101, True).model_dump(mode="json")
    best = dict(payload["best_valid_record"])
    witness = dict(payload["best_gate_crossing_record"])
    best["pair_hash"] = R2_PARENT_PAIR_HASH
    best["worst_reflected_power_fraction"] = 0.1
    witness["worst_reflected_power_fraction"] = R2_L_REQUIRED
    payload.update(
        {
            "best_valid_l": 0.1,
            "best_valid_record": best,
            "best_gate_crossing_record": witness,
        }
    )
    row = R2SeedRow.model_validate(payload)
    assert row.pass_flag is True
    assert row.best_valid_record is not None
    assert row.best_valid_record.pair_hash == R2_PARENT_PAIR_HASH

    payload["best_gate_crossing_record"] = {
        **witness,
        "worst_reflected_power_fraction": math.nextafter(
            R2_L_REQUIRED,
            math.inf,
        ),
    }
    with pytest.raises(ValidationError, match="witness"):
        R2SeedRow.model_validate(payload)


@pytest.mark.parametrize(
    "source_status",
    ("proposal_sequence_exhausted", "anchor_not_released"),
)
def test_r2_failed_row_preserves_illegal_source_terminal(source_status: str) -> None:
    row = _failed_row(101, source_status)
    assert row.execution_status == "execution_failed"
    assert row.source_run_status == source_status


def test_r2_insufficient_terminal_requires_a_frozen_limit() -> None:
    row = R2SeedRow(
        seed=101,
        run_id=f"{R2_RUN_ID_PREFIX}101",
        execution_status="insufficient_feasible_proposals",
        source_run_status="insufficient_feasible_proposals",
        accepted_count=0,
        valid_count=0,
        rejected_count=100,
        proposal_attempts=100,
        solver_mode_counts={},
        pass_flag=False,
        restart_count=0,
        terminal_consecutive_rejections=100,
        accepted_turns=_turns(0),
        effective_turns=_turns(0),
        rejection_reasons={"fixture rejection": 100},
        boundary=_boundary("none", 0),
        log_sha256="6" * 64,
        summary_sha256="7" * 64,
    )
    assert row.terminal_consecutive_rejections == 100
    payload = row.model_dump(mode="json")
    payload["terminal_consecutive_rejections"] = 99
    with pytest.raises(ValidationError, match="frozen limit"):
        R2SeedRow.model_validate(payload)


def test_r2_boundary_one_percent_is_inclusive_and_union_exact() -> None:
    stats = r2_report._boundary_field((0, 10, 989, 990, 1000), 0, 1000)
    assert (stats.lower_count, stats.upper_count, stats.either_count) == (2, 2, 4)
    assert stats.fraction == 0.8
    payload = _boundary("accepted", 100).model_dump(mode="json")
    payload["feed_gap_ratio_ppm"] = {
        "lower_count": 1,
        "upper_count": 1,
        "either_count": 1,
        "fraction": 0.01,
    }
    with pytest.raises(ValidationError, match="union"):
        BoundaryDiagnostics.model_validate(payload)


def test_r2_appendix_round_trip_preserves_complete_and_incomplete_states() -> None:
    complete = R2Appendix(
        study_status="complete",
        rows=tuple(_seed_row(seed, False) for seed in R2_SEEDS),
        baseline_diagnostics=_baseline(),
        pass_count=0,
        valid_pair_seed_count=0,
        cross_seed_gate_pass=False,
        scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
    )
    assert R2Appendix.model_validate_json(complete.model_dump_json()) == complete
    rows = (_failed_row(101),) + tuple(_not_run_row(seed) for seed in R2_SEEDS[1:])
    incomplete = R2Appendix(
        study_status="study_incomplete",
        rows=rows,
        baseline_diagnostics=_baseline(),
        matrix_exception_type="RuntimeError",
        matrix_exception_message="injected",
    )
    assert R2Appendix.model_validate_json(incomplete.model_dump_json()) == incomplete


def _write_archive_fixture(repo_root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for seed in R2_SEEDS:
        run_id = f"{R2_RUN_ID_PREFIX}{seed}"
        run_directory = repo_root / "runs" / run_id
        run_directory.mkdir(parents=True)
        log_path = run_directory / "log.jsonl"
        summary_path = run_directory / "summary.json"
        log_path.write_bytes(f"seed={seed}\n".encode())
        summary = _terminal_summary(seed)
        summary_path.write_text(summary.model_dump_json(), encoding="utf-8")
        entries.append(
            {
                "archived_at": "2026-08-30T00:00:00Z",
                "config_hash": summary.config_hash,
                "note": f"batch=semifinal-paired-r2 agent=es-r2 seed={seed}",
                "overwritten": False,
                "role": "other",
                "run_id": run_id,
                "seed": seed,
                "sha256": {
                    "log.jsonl": hashlib.sha256(log_path.read_bytes()).hexdigest(),
                    "summary.json": hashlib.sha256(
                        summary_path.read_bytes()
                    ).hexdigest(),
                },
                "solver_mode_counts": summary.solver_mode_counts,
                "steps_completed": summary.steps_completed,
            }
        )
    manifest_path = repo_root / "artifacts" / "runs" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(entries), encoding="utf-8")
    return entries


def test_r2_archive_skip_validates_entries_and_runs_full_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_archive_fixture(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_run(
        args: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == tmp_path
        assert check is True
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(r2_cli.subprocess, "run", fake_run)
    r2_cli._archive_completed_runs(tmp_path)
    assert len(calls) == 1
    assert calls[0][-1] == "--verify"


def test_r2_archive_skip_rejects_stale_manifest_entry(tmp_path: Path) -> None:
    entries = _write_archive_fixture(tmp_path)
    entries[0]["role"] = "agent-gp"
    manifest_path = tmp_path / "artifacts" / "runs" / "manifest.json"
    manifest_path.write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(RuntimeError, match="role"):
        r2_cli._archive_completed_runs(tmp_path)


def test_r2_archive_missing_entry_calls_exact_archive_then_full_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = _write_archive_fixture(tmp_path)
    manifest_path = tmp_path / "artifacts" / "runs" / "manifest.json"
    manifest_path.write_text(json.dumps(entries[:-1]), encoding="utf-8")
    target_seed = R2_SEEDS[-1]
    target_run_id = f"{R2_RUN_ID_PREFIX}{target_seed}"
    calls: list[tuple[str, ...]] = []

    def fake_run(
        args: tuple[str, ...],
        *,
        cwd: Path,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert cwd == tmp_path
        assert check is True
        calls.append(args)
        if args[-1] != "--verify":
            assert args[2:] == (
                target_run_id,
                "--role",
                "other",
                "--note",
                f"batch=semifinal-paired-r2 agent=es-r2 seed={target_seed}",
            )
            manifest_path.write_text(json.dumps(entries), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(r2_cli.subprocess, "run", fake_run)
    r2_cli._archive_completed_runs(tmp_path)
    assert len(calls) == 2
    assert calls[0][2] == target_run_id
    assert calls[1][-1] == "--verify"


@pytest.mark.asyncio
async def test_run_r2_matrix_proposer_failure_marks_seed_unstarted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProposer:
        restart_count = 0

    async def fake_runner(**kwargs: object) -> PairedRunSummary:
        config = cast(R2PairedRunConfig, kwargs["config"])
        return _terminal_summary(config.seed)

    async def unused_solver(
        _geometry: Geometry,
        _state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return SearchCurve(
            solver_name="nec2",
            solver_mode="subprocess",
            frequency_hz=frequency_hz,
            s11_db=(-0.1,) * len(frequency_hz),
        )

    monkeypatch.setattr(r2_batch, "load_r2_frozen_inputs", lambda _root: object())
    monkeypatch.setattr(
        r2_batch,
        "build_r2_config",
        lambda seed, _inputs: R2PairedRunConfig.model_validate(_config_payload(seed)),
    )

    def proposer(seed: int, _inputs: object) -> FakeProposer:
        if seed == 303:
            raise RuntimeError("injected proposer construction failure")
        return FakeProposer()

    monkeypatch.setattr(r2_batch, "build_r2_proposer", proposer)
    monkeypatch.setattr(r2_batch, "run_paired_adaptive", fake_runner)
    monkeypatch.setattr(
        r2_batch,
        "_replayed_restart_count",
        lambda _path, _seed, _inputs: 0,
    )
    with pytest.raises(R2MatrixError) as captured:
        await r2_batch.run_r2_matrix(
            tmp_path,
            solver_factory=lambda: cast(PairedSolver, unused_solver),
        )
    assert captured.value.failed_seed == 303
    assert captured.value.failed_seed_started is False
    assert tuple(
        result.summary.seed for result in captured.value.confirmed_results
    ) == (101, 202)


@pytest.mark.asyncio
async def test_run_r2_matrix_existing_terminals_use_replay_counts_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FreshProposer:
        restart_count = 0

    async def fake_runner(**kwargs: object) -> PairedRunSummary:
        config = cast(R2PairedRunConfig, kwargs["config"])
        return _terminal_summary(config.seed)

    async def unused_solver(
        _geometry: Geometry,
        _state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return SearchCurve(
            solver_name="nec2",
            solver_mode="subprocess",
            frequency_hz=frequency_hz,
            s11_db=(-0.1,) * len(frequency_hz),
        )

    for seed in R2_SEEDS:
        summary = _terminal_summary(seed)
        summary_path = tmp_path / "runs" / summary.run_id / "summary.json"
        summary_path.parent.mkdir(parents=True)
        summary_path.write_text(summary.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(r2_batch, "load_r2_frozen_inputs", lambda _root: object())
    monkeypatch.setattr(
        r2_batch,
        "build_r2_config",
        lambda seed, _inputs: R2PairedRunConfig.model_validate(_config_payload(seed)),
    )
    monkeypatch.setattr(
        r2_batch,
        "build_r2_proposer",
        lambda _seed, _inputs: FreshProposer(),
    )
    monkeypatch.setattr(r2_batch, "run_paired_adaptive", fake_runner)
    monkeypatch.setattr(
        r2_batch,
        "_replayed_restart_count",
        lambda _path, seed, _inputs: R2_SEEDS.index(seed) + 1,
    )
    results = await r2_batch.run_r2_matrix(
        tmp_path,
        solver_factory=lambda: cast(PairedSolver, unused_solver),
    )
    assert tuple(result.restart_count for result in results) == (1, 2, 3, 4, 5)


def test_r2_failure_summary_without_log_is_rejected(tmp_path: Path) -> None:
    run_id = f"{R2_RUN_ID_PREFIX}101"
    summary_path = tmp_path / "runs" / run_id / "summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(_terminal_summary(101).model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="no source log"):
        r2_report._nonterminal_row(
            tmp_path,
            101,
            "execution_failed",
            "RuntimeError",
            "injected",
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("pass_count", 1),
        ("valid_pair_seed_count", 1),
        ("cross_seed_gate_pass", True),
        ("scientific_endpoint", "seed_local_gate_crossing"),
    ),
)
def test_r2_appendix_rejects_each_aggregate_drift(
    field: str,
    bad_value: object,
) -> None:
    appendix = R2Appendix(
        study_status="complete",
        rows=tuple(_seed_row(seed, False) for seed in R2_SEEDS),
        baseline_diagnostics=_baseline(),
        pass_count=0,
        valid_pair_seed_count=0,
        cross_seed_gate_pass=False,
        scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
    )
    payload = appendix.model_dump(mode="json")
    payload[field] = bad_value
    with pytest.raises(ValidationError, match="does not recompute"):
        R2Appendix.model_validate(payload)


def test_r2_appendix_rejects_missing_duplicate_or_reordered_seed_rows() -> None:
    rows = tuple(_seed_row(seed, False) for seed in R2_SEEDS)
    base = {
        "study_status": "complete",
        "baseline_diagnostics": _baseline(),
        "pass_count": 0,
        "valid_pair_seed_count": 0,
        "cross_seed_gate_pass": False,
        "scientific_endpoint": "no_gate_crossing_observed_under_frozen_r2",
    }
    for bad_rows in (rows[:-1], (rows[0], rows[0], *rows[2:]), tuple(reversed(rows))):
        with pytest.raises(ValidationError, match="ordered five-seed"):
            R2Appendix(rows=bad_rows, **base)


def test_r2_report_renders_full_audit_diagnostics() -> None:
    appendix = R2Appendix(
        study_status="complete",
        rows=tuple(_seed_row(seed, False) for seed in R2_SEEDS),
        baseline_diagnostics=_baseline(),
        pass_count=0,
        valid_pair_seed_count=0,
        cross_seed_gate_pass=False,
        scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
    )
    report = r2_report.render_r2_report(appendix)
    assert "## Per-seed audit diagnostics" in report
    assert "Gate-crossing witness" in report
    assert "Boundary pool" in report
    assert "Accepted turn counts" in report
    assert "Rejection reasons" in report
    assert "Source SHA-256" in report
    assert report.endswith("\n")
    assert not report.endswith("\n\n")
    assert all(line == line.rstrip() for line in report.splitlines())
    assert "\r" not in report


def test_r2_cli_stdout_contains_all_frozen_diagnostic_families(
    capsys: pytest.CaptureFixture[str],
) -> None:
    appendix = R2Appendix(
        study_status="complete",
        rows=tuple(_seed_row(seed, False) for seed in R2_SEEDS),
        baseline_diagnostics=_baseline(),
        pass_count=0,
        valid_pair_seed_count=0,
        cross_seed_gate_pass=False,
        scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
    )
    r2_cli._print_appendix(appendix)
    output = capsys.readouterr().out
    assert "source_status=completed" in output
    assert "short_segment_rejections=" in output
    assert "accepted_turn_count_distribution=" in output
    assert "effective_turn_count_distribution=" in output
    assert "boundary_1pct_by_dim=" in output
    assert "valid_pair_seed_count=0/5" in output
    assert "cross_seed_gate_pass=False" in output


def test_r2_output_writer_is_lf_only_and_cleans_failed_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appendix = R2Appendix(
        study_status="complete",
        rows=tuple(_seed_row(seed, False) for seed in R2_SEEDS),
        baseline_diagnostics=_baseline(),
        pass_count=0,
        valid_pair_seed_count=0,
        cross_seed_gate_pass=False,
        scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
    )
    r2_report.write_r2_outputs(tmp_path, appendix)
    for relative in (r2_report.R2_APPENDIX_PATH, r2_report.R2_REPORT_PATH):
        assert b"\r" not in (tmp_path / relative).read_bytes()

    target = tmp_path / "atomic.json"

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(r2_report.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failure"):
        r2_report._atomic_write(target, b"payload\n")
    assert not target.exists()
    assert not target.with_suffix(".json.tmp").exists()


def test_r2_cli_post_matrix_failure_does_not_publish_incomplete_science(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appendix = R2Appendix(
        study_status="complete",
        rows=tuple(_seed_row(seed, False) for seed in R2_SEEDS),
        baseline_diagnostics=_baseline(),
        pass_count=0,
        valid_pair_seed_count=0,
        cross_seed_gate_pass=False,
        scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
    )
    calls: list[object] = []

    async def fake_matrix(_root: Path) -> tuple[R2CellResult, ...]:
        return tuple(_cell(seed) for seed in R2_SEEDS)

    def fake_build(
        _root: Path,
        *,
        matrix_error: R2MatrixError | None = None,
        restart_counts: dict[int, int] | None = None,
    ) -> R2Appendix:
        calls.append(matrix_error)
        assert restart_counts == dict.fromkeys(R2_SEEDS, 1)
        return appendix

    monkeypatch.setattr(r2_cli, "run_r2_matrix", fake_matrix)
    monkeypatch.setattr(r2_cli, "build_r2_appendix", fake_build)
    monkeypatch.setattr(r2_cli, "write_r2_outputs", lambda _root, _appendix: None)
    monkeypatch.setattr(
        r2_cli,
        "_archive_completed_runs",
        lambda _root: (_ for _ in ()).throw(RuntimeError("archive failed")),
    )
    monkeypatch.setattr(
        r2_cli.sys,
        "argv",
        ["paired_r2_batch.py", "--repo-root", str(tmp_path)],
    )
    assert r2_cli.main() == 1
    assert calls == [None]


@pytest.mark.parametrize(
    ("pass_count", "endpoint"),
    (
        (0, "no_gate_crossing_observed_under_frozen_r2"),
        (1, "seed_local_gate_crossing"),
        (2, "seed_local_gate_crossing"),
        (3, "seed_local_gate_crossing"),
        (4, "cross_seed_gate_crossing"),
        (5, "cross_seed_gate_crossing"),
    ),
)
def test_r2_appendix_recomputes_mutually_exclusive_endpoint(
    pass_count: int,
    endpoint: str,
) -> None:
    rows = tuple(
        _seed_row(seed, index < pass_count)
        for index, seed in enumerate(R2_SEEDS)
    )
    appendix = R2Appendix.model_validate(
        {
            "study_status": "complete",
            "rows": rows,
            "baseline_diagnostics": _baseline(),
            "pass_count": pass_count,
            "valid_pair_seed_count": pass_count,
            "cross_seed_gate_pass": pass_count >= 4,
            "scientific_endpoint": endpoint,
        }
    )
    assert appendix.scientific_endpoint == endpoint
    payload = appendix.model_dump(mode="json")
    payload["pass_count"] = (pass_count + 1) % 6
    with pytest.raises(ValidationError, match="does not recompute"):
        R2Appendix.model_validate(payload)


def test_incomplete_appendix_forbids_scientific_aggregate() -> None:
    rows = [_seed_row(seed, False) for seed in R2_SEEDS]
    failed = rows[0].model_dump(mode="json")
    failed.update(
        {
            "execution_status": "execution_failed",
            "pass_flag": None,
            "restart_count": None,
            "terminal_consecutive_rejections": None,
            "best_gate_crossing_record": None,
            "exception_type": "RuntimeError",
            "exception_message": "injected",
        }
    )
    rows[0] = R2SeedRow.model_validate(failed)
    with pytest.raises(ValidationError, match="cannot carry scientific aggregates"):
        R2Appendix(
            study_status="study_incomplete",
            rows=tuple(rows),
            baseline_diagnostics=_baseline(),
            matrix_exception_type="RuntimeError",
            matrix_exception_message="injected",
            pass_count=0,
            valid_pair_seed_count=0,
            cross_seed_gate_pass=False,
            scientific_endpoint="no_gate_crossing_observed_under_frozen_r2",
        )


def test_existing_science_blobs_and_archived_source_bytes_are_unchanged() -> None:
    root = _repo_root()
    assert (
        root / "artifacts/runs/semifinal-paired-es-warm-s101/log.jsonl"
    ).read_bytes()
    assert hashlib.sha256(
        (
            root / "artifacts/runs/semifinal-paired-es-warm-s101/log.jsonl"
        ).read_bytes()
    ).hexdigest() == R2_PARENT_SOURCE_LOG_SHA256
    for path, expected_blob in FROZEN_SCIENCE_BLOBS.items():
        process = subprocess.run(
            ("git", "hash-object", f"--path={path.as_posix()}", path.as_posix()),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        assert process.stdout.strip() == expected_blob
