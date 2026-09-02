from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from yaf_ai.exploration import paired_b_completion_batch as batch
from yaf_ai.exploration.paired_b_completion_agents import (
    ES_AGENT,
    RANDOM_AGENT,
    BCompletionFatalRejectionError,
)
from yaf_ai.exploration.paired_b_completion_coordinates import P01, P02
from yaf_ai.exploration.paired_b_completion_gates import (
    FROZEN_PARENTS,
    PREREGISTRATION_COMMIT,
    RUNTIME_PATHS,
    SOURCE_EVIDENCE_COMMIT,
    SOURCE_MANIFEST_ENTRY_COUNT,
    SOURCE_MANIFEST_SHA256,
    BCompletionGateInputs,
    canonical_curve_sha256,
)
from yaf_ai.exploration.paired_feasible_gates import (
    BUDGET_CONFIG_HASH,
    BUDGET_SOURCE_COMMIT,
    BUDGET_SUMMARY_SHA256,
)
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    SearchCurve,
    build_state_geometry,
)
from yaf_ai.exploration.paired_runner import PairedRunSummary, _config_hash  # noqa: PLC2701


def _inputs() -> batch.BCompletionMatrixInputs:
    implementation = "d" * 40
    execution = "e" * 40
    runtime = {path.as_posix(): "a" * 40 for path in RUNTIME_PATHS}
    gates = BCompletionGateInputs(
        source_evidence_commit=SOURCE_EVIDENCE_COMMIT,
        preregistration_commit=PREREGISTRATION_COMMIT,
        implementation_commit=implementation,
        execution_commit=execution,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_manifest_entry_count=SOURCE_MANIFEST_ENTRY_COUNT,
        accepted_record_count=6_000,
        stage_b_run_count=10,
        parents=FROZEN_PARENTS,
        budget_source_commit=BUDGET_SOURCE_COMMIT,
        budget_summary_sha256=BUDGET_SUMMARY_SHA256,
        budget_config_hash=BUDGET_CONFIG_HASH,
        frozen_science_blobs={"frozen.py": "b" * 40},
        runtime_path_blobs=runtime,
        clean_tracked_code=True,
    )
    return batch.BCompletionMatrixInputs(
        gates=gates,
        certificate_evidence_commit=execution,
        certificate_summary_sha256="1" * 64,
        certificate_report_sha256="2" * 64,
        conditional_implementation_blobs=runtime,
    )


def _summary(config: batch.BCompletionRunConfig) -> PairedRunSummary:
    now = datetime.now(UTC)
    return PairedRunSummary(
        run_id=config.run_id,
        started_at=now,
        finished_at=now,
        seed=config.seed,
        config_hash=_config_hash(config),
        config=config.model_dump(mode="json"),
        steps_completed=batch.EVALUATION_BUDGET,
        evaluation_budget=batch.EVALUATION_BUDGET,
        solver_mode_counts={"subprocess": 600},
        rejected_proposals=0,
        proposal_attempts=batch.EVALUATION_BUDGET,
        status="completed",
        termination_reason="accepted paired-evaluation budget completed",
    )


def _curve(
    frequencies: tuple[float, ...],
    *,
    depth: float = -10.0,
) -> SearchCurve:
    return SearchCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=tuple(depth for _ in frequencies),
    )


def test_matrix_is_the_exact_twenty_cell_preregistered_order() -> None:
    assert len(batch.FROZEN_MATRIX) == 20
    assert tuple(cell.parent_id for cell in batch.FROZEN_MATRIX[:10]) == ("p01",) * 10
    assert tuple(cell.parent_id for cell in batch.FROZEN_MATRIX[10:]) == ("p02",) * 10
    assert tuple(cell.agent for cell in batch.FROZEN_MATRIX[:5]) == (RANDOM_AGENT,) * 5
    assert tuple(cell.agent for cell in batch.FROZEN_MATRIX[5:10]) == (ES_AGENT,) * 5
    assert tuple(cell.seed for cell in batch.FROZEN_MATRIX[:5]) == (101, 202, 303, 404, 505)
    assert batch.FROZEN_MATRIX[0].run_id == ("semifinal-paired-b-completion-p01-random-s101")
    assert batch.FROZEN_MATRIX[-1].run_id == ("semifinal-paired-b-completion-p02-es-s505")


def test_all_twenty_configs_are_unique_and_carry_complete_parent_binding() -> None:
    inputs = _inputs()
    configs = tuple(batch.build_run_config(cell, inputs) for cell in batch.FROZEN_MATRIX)
    assert len({_config_hash(config) for config in configs}) == 20
    assert all(config.evaluation_budget == 300 for config in configs)
    assert all(config.max_total_proposal_attempts == 300 for config in configs)
    assert all(config.max_consecutive_rejections == 100 for config in configs)
    assert configs[0].bound_parent == FROZEN_PARENTS[0]
    assert configs[-1].bound_parent == FROZEN_PARENTS[1]
    assert configs[0].conditional_implementation_blobs == inputs.gates.runtime_path_blobs


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("evaluation_budget", 301),
        ("seed", 999),
        ("run_id", "wrong"),
        ("agent_code", 99),
        ("parent_code", 2),
        ("anchor_released", True),
        ("max_total_proposal_attempts", 301),
        ("preregistration_commit", "short"),
        ("warm_parent_run_id", "forbidden"),
    ),
)
def test_config_validator_rejects_each_frozen_field_change(
    field: str,
    value: object,
) -> None:
    config = batch.build_run_config(batch.FROZEN_MATRIX[0], _inputs())
    payload = config.model_dump(mode="python")
    payload[field] = value
    with pytest.raises(ValidationError):
        batch.BCompletionRunConfig.model_validate(payload)


def test_config_rejects_runtime_blob_map_missing_one_path() -> None:
    config = batch.build_run_config(batch.FROZEN_MATRIX[0], _inputs())
    payload = config.model_dump(mode="python")
    blobs = dict(config.conditional_implementation_blobs)
    blobs.pop(next(iter(blobs)))
    payload["conditional_implementation_blobs"] = blobs
    with pytest.raises(ValidationError, match="runtime blob map"):
        batch.BCompletionRunConfig.model_validate(payload)


@pytest.mark.parametrize("parent_id", ("p01", "p02"))
def test_parent_decoder_changes_only_a_and_is_total(
    parent_id: batch.ParentID,
) -> None:
    frozen = P01 if parent_id == "p01" else P02
    decoder = batch.build_parent_decoder(parent_id)
    proposal = decoder((0.25, 0.75), RANDOM_AGENT)
    assert proposal.hardware == frozen.hardware
    assert proposal.state_b == frozen.state_b
    assert proposal.state_a.state == "A"
    assert proposal.proposer == RANDOM_AGENT


def test_proposers_are_parent_bound_and_first_rejection_is_fatal() -> None:
    inputs = _inputs()
    for cell in (batch.FROZEN_MATRIX[0], batch.FROZEN_MATRIX[5]):
        proposer = batch.build_proposer(cell, inputs)
        proposal = proposer.propose()
        assert proposal.hardware == P01.hardware
        assert proposal.state_b == P01.state_b
        with pytest.raises(BCompletionFatalRejectionError):
            proposer.reject(proposal)


def test_parent_bound_solver_accepts_exact_subprocess_b_curve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curve = _curve(STATE_B_FREQUENCIES_HZ)
    digest = canonical_curve_sha256(curve.model_dump(mode="json"))
    monkeypatch.setattr(batch, "_source_curve_hash", lambda _parent_id: digest)

    async def fake_solver(
        _geometry: object,
        _state: str,
        _frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return curve

    solver = batch.ParentBoundStrictSubprocessSolver(fake_solver, P01)
    result = asyncio.run(
        solver(build_state_geometry(P01.hardware, P01.state_b), "B", STATE_B_FREQUENCIES_HZ)
    )
    assert result == curve


def test_parent_bound_solver_rejects_b_curve_hash_before_record_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _curve(STATE_B_FREQUENCIES_HZ, depth=-10.0)
    actual = _curve(STATE_B_FREQUENCIES_HZ, depth=-9.0)
    monkeypatch.setattr(
        batch,
        "_source_curve_hash",
        lambda _parent_id: canonical_curve_sha256(expected.model_dump(mode="json")),
    )

    async def fake_solver(
        _geometry: object,
        _state: str,
        _frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return actual

    solver = batch.ParentBoundStrictSubprocessSolver(fake_solver, P01)
    with pytest.raises(batch.BCompletionStateBReproductionError) as captured:
        asyncio.run(
            solver(
                build_state_geometry(P01.hardware, P01.state_b),
                "B",
                STATE_B_FREQUENCIES_HZ,
            )
        )
    assert (
        captured.value.expected_hashes["state_b_curve_sha256"]
        != (captured.value.actual_hashes["state_b_curve_sha256"])
    )


def test_parent_bound_solver_rejects_non_subprocess_a_curve() -> None:
    curve = _curve(STATE_A_FREQUENCIES_HZ).model_copy(update={"solver_mode": "fallback_analytical"})

    async def fake_solver(
        _geometry: object,
        _state: str,
        _frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return curve

    solver = batch.ParentBoundStrictSubprocessSolver(fake_solver, P01)
    with pytest.raises(batch.BCompletionBatchError, match="subprocess"):
        asyncio.run(
            solver(
                build_state_geometry(P01.hardware, P01.state_b),
                "A",
                STATE_A_FREQUENCIES_HZ,
            )
        )


def test_exact_resume_rejects_a_terminal_after_a_gap(tmp_path: Path) -> None:
    inputs = _inputs()
    configs = tuple(batch.build_run_config(cell, inputs) for cell in batch.FROZEN_MATRIX[:2])
    later = tmp_path / configs[1].run_id
    later.mkdir(parents=True)
    (later / "summary.json").write_text(_summary(configs[1]).model_dump_json(), encoding="utf-8")
    with pytest.raises(batch.BCompletionBatchError, match="fixed-order prefix"):
        batch._validate_exact_resume(tmp_path, configs)  # noqa: SLF001


def test_atomic_failure_writer_round_trips_without_temporary_file(tmp_path: Path) -> None:
    failure = batch.MatrixFailureRecord(
        study_status="matrix_execution_failed",
        failed_run_id=batch.FROZEN_MATRIX[0].run_id,
        accepted_count=0,
        rejected_count=0,
        proposal_attempts=0,
        partial_log_sha256=hashlib.sha256(b"").hexdigest(),
        partial_log_bytes=0,
        partial_log_lines=0,
        exception_class="RuntimeError",
        exception_message="boom",
        completed_prefix=(),
    )
    target = tmp_path / "matrix_failure.json"
    batch._atomic_write_failure(target, failure)  # noqa: SLF001
    assert batch.MatrixFailureRecord.model_validate_json(target.read_bytes()) == failure
    assert not target.with_suffix(".json.tmp").exists()
    assert b"\r" not in target.read_bytes()


def test_matrix_failure_persists_b_hashes_and_forbids_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs()
    expected = {
        "hardware_hash": "1" * 64,
        "state_b_geometry_hash": "2" * 64,
        "state_b_curve_sha256": "3" * 64,
    }
    actual = {**expected, "state_b_curve_sha256": "4" * 64}
    calls = 0

    def fake_inputs(*_args: object, **_kwargs: object) -> batch.BCompletionMatrixInputs:
        return inputs

    async def fail_runner(**_kwargs: object) -> PairedRunSummary:
        nonlocal calls
        calls += 1
        raise batch.BCompletionStateBReproductionError(
            "B changed", expected_hashes=expected, actual_hashes=actual
        )

    async def fake_solver(
        _geometry: object,
        _state: str,
        frequencies: tuple[float, ...],
    ) -> SearchCurve:
        return _curve(frequencies)

    monkeypatch.setattr(batch, "load_matrix_inputs", fake_inputs)
    monkeypatch.setattr(batch, "_validate_exact_resume", lambda *_args: ())
    monkeypatch.setattr(batch, "run_paired_adaptive", fail_runner)
    with pytest.raises(batch.BCompletionMatrixError) as captured:
        asyncio.run(
            batch.run_b_completion_matrix(
                tmp_path,
                implementation_commit="d" * 40,
                certificate_evidence_commit="e" * 40,
                solver_factory=lambda: fake_solver,
            )
        )
    assert captured.value.failure.study_status == "state_b_reproduction_failed"
    assert captured.value.failure.expected_b_hashes == expected
    marker = tmp_path / batch.MATRIX_FAILURE_PATH
    assert marker.is_file()
    assert json.loads(marker.read_text(encoding="utf-8"))["actual_b_hashes"] == actual
    with pytest.raises(batch.BCompletionBatchError, match="terminal"):
        asyncio.run(
            batch.run_b_completion_matrix(
                tmp_path,
                implementation_commit="d" * 40,
                certificate_evidence_commit="e" * 40,
                solver_factory=lambda: fake_solver,
            )
        )
    assert calls == 1


def test_matrix_orchestration_uses_exact_fixed_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs()
    observed: list[str] = []

    def fake_inputs(*_args: object, **_kwargs: object) -> batch.BCompletionMatrixInputs:
        return inputs

    async def fake_run(**kwargs: Any) -> PairedRunSummary:
        config = kwargs["config"]
        assert isinstance(config, batch.BCompletionRunConfig)
        observed.append(config.run_id)
        return _summary(config)

    async def fake_solver(
        _geometry: object,
        _state: str,
        frequencies: tuple[float, ...],
    ) -> SearchCurve:
        return _curve(frequencies)

    monkeypatch.setattr(batch, "load_matrix_inputs", fake_inputs)
    monkeypatch.setattr(batch, "_validate_exact_resume", lambda *_args: ())
    monkeypatch.setattr(batch, "_validate_persisted_log", lambda *_args: 300)
    monkeypatch.setattr(batch, "run_paired_adaptive", fake_run)
    results = asyncio.run(
        batch.run_b_completion_matrix(
            tmp_path,
            implementation_commit="d" * 40,
            certificate_evidence_commit="e" * 40,
            solver_factory=lambda: fake_solver,
        )
    )
    assert observed == [cell.run_id for cell in batch.FROZEN_MATRIX]
    assert tuple(result.summary.run_id for result in results) == tuple(observed)
