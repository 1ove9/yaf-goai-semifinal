"""Fail-closed tests for the exact-support Stage-B matrix."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from yaf_ai.exploration import paired_feasible_batch as batch
from yaf_ai.exploration.paired_feasible_agents import (
    StratifiedAgentDiagnostics,
    StratifiedIslandDiagnostics,
)
from yaf_ai.exploration.paired_feasible_gates import StageAGateError
from yaf_ai.exploration.paired_meander import PairedSolver
from yaf_ai.exploration.paired_runner import PairedRunSummary, _config_hash


def _inputs() -> batch.StageBFrozenInputs:
    return batch.StageBFrozenInputs(
        execution_commit="a" * 40,
        implementation_commit="b" * 40,
        stage_a_evidence_commit="c" * 40,
        stage_a_summary_sha256="d" * 64,
        stage_a_report_sha256="e" * 64,
    )


def _diagnostics(agent: batch.StageBAgent) -> StratifiedAgentDiagnostics:
    label = (
        "random-stratified-v1"
        if agent == batch.RANDOM_AGENT
        else "es-stratified-v1"
    )
    return StratifiedAgentDiagnostics(
        agent=label,  # type: ignore[arg-type]
        accepted_count=600,
        islands=tuple(
            StratifiedIslandDiagnostics(
                turn_count=turn,
                accepted_count=150,
                restart_count=0,
                parent_pair_hash=None,
                sigma=None,
                consecutive_non_improvements=None,
            )
            for turn in (3, 4, 5, 6)
        ),
    )


def _summary(agent: batch.StageBAgent, seed: int) -> PairedRunSummary:
    config = batch.build_stage_b_config(agent, seed, _inputs())
    now = datetime.now(UTC)
    return PairedRunSummary(
        run_id=config.run_id,
        started_at=now,
        finished_at=now,
        seed=seed,
        config_hash=_config_hash(config),
        config=config.model_dump(mode="json"),
        steps_completed=600,
        evaluation_budget=600,
        solver_mode_counts={"subprocess": 1200},
        rejected_proposals=0,
        proposal_attempts=600,
        status="completed",
        termination_reason="accepted paired-evaluation budget completed",
    )


def test_matrix_and_config_identity_are_frozen() -> None:
    assert tuple(
        (agent, seed)
        for agent in (batch.RANDOM_AGENT, batch.ES_AGENT)
        for seed in (101, 202, 303, 404, 505)
    ) == batch.MATRIX
    for agent, seed in batch.MATRIX:
        config = batch.build_stage_b_config(agent, seed, _inputs())
        assert config.evaluation_budget == 600
        assert config.quota_per_turn == 150
        assert config.turn_order == (3, 4, 5, 6)
        assert config.max_total_proposal_attempts == 9000
        assert config.max_consecutive_rejections == 100
        assert not config.anchor_released
        assert not config.openems_cross_check_authorized
        assert config.agent_code == (1 if agent == batch.RANDOM_AGENT else 2)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evaluation_budget", 599),
        ("quota_per_turn", 149),
        ("mapping_version", "changed"),
        ("stage_a_evidence_commit", "short"),
        ("max_total_proposal_attempts", 8999),
        ("anchor_released", True),
    ],
)
def test_config_rejects_one_field_drift(field: str, value: object) -> None:
    payload = batch.build_stage_b_config(
        batch.RANDOM_AGENT, 101, _inputs()
    ).model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValueError):
        batch.StageBRunConfig.model_validate(payload)


def test_stage_a_commit_is_required_as_a_full_hash(tmp_path: Path) -> None:
    with pytest.raises(StageAGateError, match="full hash"):
        batch.load_stage_b_inputs(tmp_path, "UNSET")


def test_v2_adapter_exposes_v2_labels_and_retains_rejection_turn() -> None:
    proposer = batch.build_stage_b_proposer(batch.RANDOM_AGENT, 101)
    first = proposer.propose()
    assert first.proposer == batch.RANDOM_AGENT
    assert first.hardware.turn_count == 3
    proposer.reject(first)
    second = proposer.propose()
    assert second.proposer == batch.RANDOM_AGENT
    assert second.hardware.turn_count == 3


def test_cell_result_requires_the_sole_legal_terminal() -> None:
    result = batch.StageBCellResult(
        summary=_summary(batch.ES_AGENT, 101),
        diagnostics=_diagnostics(batch.ES_AGENT),
    )
    assert result.summary.steps_completed == 600
    bad = result.summary.model_copy(update={"solver_mode_counts": {"subprocess": 1198}})
    with pytest.raises(ValueError, match="sole legal"):
        batch.StageBCellResult(summary=bad, diagnostics=result.diagnostics)
    with pytest.raises(ValueError, match="sole legal"):
        batch.StageBCellResult(
            summary=result.summary,
            diagnostics=_diagnostics(batch.RANDOM_AGENT),
        )
    bad_termination = result.summary.model_copy(
        update={"termination_reason": "completed for a different reason"}
    )
    with pytest.raises(ValueError, match="sole legal"):
        batch.StageBCellResult(
            summary=bad_termination,
            diagnostics=result.diagnostics,
        )
    swapped_islands = StratifiedAgentDiagnostics(
        agent=result.diagnostics.agent,
        accepted_count=result.diagnostics.accepted_count,
        islands=(
            result.diagnostics.islands[1],
            result.diagnostics.islands[0],
            result.diagnostics.islands[2],
            result.diagnostics.islands[3],
        ),
    )
    with pytest.raises(ValueError, match="sole legal"):
        batch.StageBCellResult(
            summary=result.summary,
            diagnostics=swapped_islands,
        )


def test_matrix_error_requires_the_exact_confirmed_prefix() -> None:
    first = batch.StageBCellResult(
        summary=_summary(batch.RANDOM_AGENT, 101),
        diagnostics=_diagnostics(batch.RANDOM_AGENT),
    )
    error = batch.StageBMatrixError(
        RuntimeError("stop"),
        failed_cell=(batch.RANDOM_AGENT, 202),
        failed_cell_started=True,
        confirmed_results=(first,),
    )
    assert error.failed_cell == (batch.RANDOM_AGENT, 202)
    with pytest.raises(ValueError, match="exact matrix prefix"):
        batch.StageBMatrixError(
            RuntimeError("stop"),
            failed_cell=(batch.RANDOM_AGENT, 303),
            failed_cell_started=True,
            confirmed_results=(first,),
        )


@pytest.mark.asyncio
async def test_provenance_failure_happens_before_solver_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False

    def fail_gate(_root: Path, _commit: str) -> batch.StageBFrozenInputs:
        raise StageAGateError("injected gate failure")

    def solver_factory() -> PairedSolver:
        nonlocal constructed
        constructed = True
        raise AssertionError("solver must not be constructed")

    monkeypatch.setattr(batch, "load_stage_b_inputs", fail_gate)
    with pytest.raises(batch.StageBMatrixError) as captured:
        await batch.run_stage_b_matrix(
            tmp_path,
            stage_a_evidence_commit="c" * 40,
            solver_factory=solver_factory,
        )
    assert captured.value.failed_cell is None
    assert not constructed


@pytest.mark.asyncio
async def test_matrix_runs_random_then_es_and_accepts_only_completed_terminals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, int]] = []

    class NoopSolver:
        async def __call__(self, *_args: object) -> object:
            raise AssertionError("mock runner must not call solver")

    async def fake_runner(**kwargs: object) -> PairedRunSummary:
        config = cast(batch.StageBRunConfig, kwargs["config"])
        observed.append((config.agent, config.seed))
        return _summary(config.agent, config.seed)

    monkeypatch.setattr(batch, "load_stage_b_inputs", lambda _root, _commit: _inputs())
    monkeypatch.setattr(batch, "run_paired_adaptive", fake_runner)
    monkeypatch.setattr(
        batch,
        "_replayed_diagnostics",
        lambda _path, agent, _seed: _diagnostics(agent),
    )
    monkeypatch.setattr(
        batch,
        "build_stage_b_proposer",
        lambda agent, _seed: cast(object, SimpleDiagnostics(agent)),
    )
    results = await batch.run_stage_b_matrix(
        tmp_path,
        stage_a_evidence_commit="c" * 40,
        solver_factory=cast(Callable[[], PairedSolver], lambda: NoopSolver()),
    )
    assert observed == list(batch.MATRIX)
    assert len(results) == 10


class SimpleDiagnostics:
    """Minimal proposer surface for the matrix orchestration test."""

    def __init__(self, agent: batch.StageBAgent) -> None:
        self.diagnostics = _diagnostics(agent)
