"""Regression tests for the frozen semifinal paired-agent batch."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from yaf_ai.exploration import paired_batch
from yaf_ai.exploration.paired_batch import (
    BATCH_PREREGISTRATION_COMMIT,
    BUDGET_SOURCE_CONFIG_HASH,
    BUDGET_SOURCE_SUMMARY_SHA256,
    FROZEN_AGENT_CELLS,
    FROZEN_EVALUATION_BUDGET,
    MANUAL_BASELINE_COMMIT,
    MANUAL_LOG_PATH,
    PREFLIGHT_SUMMARY_PATH,
    WARM_PARENT_DOCUMENT_SHA256,
    WARM_PARENT_HARDWARE_GRID_INDEX,
    WARM_PARENT_HARDWARE_HASH,
    WARM_PARENT_PAIR_GRID_INDEX,
    WARM_PARENT_PAIR_HASH,
    WARM_PARENT_PATH,
    WARM_PARENT_RUN_ID,
    WARM_PARENT_SEARCH_SCORE,
    WARM_PARENT_SOURCE_STEP,
    WARM_PARENT_STATE_A_HASH,
    WARM_PARENT_STATE_B_HASH,
    PairedBatchError,
    _StrictSubprocessSolver,
    _validate_parent,
    _validate_preflight,
    build_agent_proposer,
    build_agent_run_config,
    load_frozen_batch_inputs,
    run_frozen_agent_matrix,
)
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    PairedSolver,
    SearchCurve,
    StateLabel,
    audit_trajectory,
    pair_hash,
)
from yaf_ai.exploration.paired_runner import (
    MANUAL_BASELINE_RUN_ID_PREFIX,
    PREFLIGHT_RUN_ID_PREFIX,
    PairedEvaluationRecord,
    PairedRunConfig,
    PairedRunError,
    _config_hash,
    freeze_candidate,
    run_paired_adaptive,
)
from yaf_core.domain.geometry import Geometry


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_frozen_agent_matrix_is_exact_and_ordered() -> None:
    assert [
        (cell.run_id, cell.agent, cell.seed) for cell in FROZEN_AGENT_CELLS
    ] == [
        ("semifinal-paired-random-s101", "random", 101),
        ("semifinal-paired-random-s202", "random", 202),
        ("semifinal-paired-random-s303", "random", 303),
        ("semifinal-paired-es-cold-s101", "es-cold", 101),
        ("semifinal-paired-es-cold-s202", "es-cold", 202),
        ("semifinal-paired-es-cold-s303", "es-cold", 303),
        ("semifinal-paired-es-warm-s101", "es-warm", 101),
        ("semifinal-paired-es-warm-s202", "es-warm", 202),
        ("semifinal-paired-es-warm-s303", "es-warm", 303),
    ]
    assert FROZEN_EVALUATION_BUDGET == 300
    source = (_repo_root() / "scripts/paired_batch.py").read_text(encoding="utf-8")
    assert "--budget" not in source
    assert "--seeds" not in source
    assert 'YAF_NO_FALLBACK"] = "1"' in source


def test_archived_parent_and_budget_sources_pass_all_gates() -> None:
    inputs = load_frozen_batch_inputs(_repo_root())
    assert len(inputs.execution_commit) == 40
    assert inputs.warm_parent.pair_hash == WARM_PARENT_PAIR_HASH
    assert inputs.warm_parent_source.step_index == WARM_PARENT_SOURCE_STEP
    assert inputs.preflight.budget == FROZEN_EVALUATION_BUDGET
    assert inputs.preflight.config_hash == BUDGET_SOURCE_CONFIG_HASH


def test_parent_and_budget_byte_tampering_fails_before_use() -> None:
    root = _repo_root()
    parent = (root / WARM_PARENT_PATH).read_bytes()
    log = (root / MANUAL_LOG_PATH).read_bytes()
    summary = (root / PREFLIGHT_SUMMARY_PATH).read_bytes()
    with pytest.raises(PairedBatchError, match="SHA-256"):
        _validate_parent(parent + b" ", log)
    with pytest.raises(PairedBatchError, match="SHA-256"):
        _validate_preflight(summary + b" ")


def test_every_warm_config_carries_complete_parent_and_budget_provenance() -> None:
    inputs = load_frozen_batch_inputs(_repo_root())
    hashes: list[str] = []
    for cell in FROZEN_AGENT_CELLS:
        config = build_agent_run_config(cell, inputs)
        assert config.evaluation_budget == 300
        assert config.preregistration_commit == BATCH_PREREGISTRATION_COMMIT
        assert config.execution_commit == inputs.execution_commit
        assert config.budget_source_summary_sha256 == BUDGET_SOURCE_SUMMARY_SHA256
        assert config.budget_source_config_hash == BUDGET_SOURCE_CONFIG_HASH
        if cell.agent == "es-warm":
            assert config.manual_baseline_commit == MANUAL_BASELINE_COMMIT
            assert config.warm_parent_run_id == WARM_PARENT_RUN_ID
            assert config.warm_parent_pair_hash == WARM_PARENT_PAIR_HASH
            assert config.warm_parent_document_sha256 == WARM_PARENT_DOCUMENT_SHA256
            assert config.warm_parent_hardware_hash == WARM_PARENT_HARDWARE_HASH
            assert config.warm_parent_state_a_geometry_hash == WARM_PARENT_STATE_A_HASH
            assert config.warm_parent_state_b_geometry_hash == WARM_PARENT_STATE_B_HASH
            assert config.warm_parent_step_index == WARM_PARENT_SOURCE_STEP
            assert (
                config.warm_parent_hardware_grid_index
                == WARM_PARENT_HARDWARE_GRID_INDEX
            )
            assert config.warm_parent_pair_grid_index == WARM_PARENT_PAIR_GRID_INDEX
            assert config.warm_parent_search_score == WARM_PARENT_SEARCH_SCORE
        else:
            assert config.manual_baseline_commit is None
            assert config.warm_parent_document_sha256 is None
        hashes.append(_config_hash(config))
    assert len(set(hashes)) == 9
    warm = build_agent_run_config(FROZEN_AGENT_CELLS[6], inputs)
    changed = warm.model_copy(update={"warm_parent_step_index": 289})
    assert _config_hash(changed) != _config_hash(warm)


def test_nonwarm_config_rejects_any_warm_parent_field() -> None:
    with pytest.raises(ValidationError, match="only es-warm"):
        PairedRunConfig(
            run_id="bad-random",
            agent="random",
            seed=101,
            evaluation_budget=300,
            anchor_released=False,
            openems_cross_check_authorized=False,
            preregistration_commit=BATCH_PREREGISTRATION_COMMIT,
            manual_baseline_commit=MANUAL_BASELINE_COMMIT,
        )


def test_first_valid_warm_budget_item_is_a_mutation_for_all_seeds() -> None:
    inputs = load_frozen_batch_inputs(_repo_root())
    rejection_counts: list[int] = []
    for cell in FROZEN_AGENT_CELLS[6:]:
        proposer = build_agent_proposer(cell, inputs)
        rejected = 0
        while True:
            proposal = proposer.propose()
            if audit_trajectory(proposal).valid:
                break
            proposer.reject(proposal)
            rejected += 1
        assert pair_hash(proposal) != WARM_PARENT_PAIR_HASH
        rejection_counts.append(rejected)
    assert rejection_counts[0] == 17


class _NativeSolver:
    async def __call__(
        self,
        _geometry: Geometry,
        state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        return SearchCurve(
            solver_name="nec2",
            solver_mode="native",
            frequency_hz=frequency_hz,
            s11_db=tuple(-1.0 for _ in frequency_hz),
        )


@pytest.mark.asyncio
async def test_batch_boundary_rejects_non_subprocess_curve() -> None:
    strict = _StrictSubprocessSolver(cast(PairedSolver, _NativeSolver()))
    frequencies = STATE_A_FREQUENCIES_HZ
    with pytest.raises(PairedBatchError, match="subprocess"):
        await strict(Geometry(nodes=(), edges=()), "A", frequencies)


@pytest.mark.asyncio
async def test_input_failure_precedes_solver_factory_and_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_inputs(_root: Path) -> None:
        raise PairedBatchError("injected parent failure")

    def solver_factory() -> PairedSolver:
        nonlocal called
        called = True
        return cast(PairedSolver, _NativeSolver())

    monkeypatch.setattr(paired_batch, "load_frozen_batch_inputs", fail_inputs)
    with pytest.raises(PairedBatchError, match="injected parent"):
        await run_frozen_agent_matrix(tmp_path, solver_factory=solver_factory)
    assert not called
    assert not (tmp_path / "runs").exists()


@pytest.mark.asyncio
async def test_matrix_continues_frozen_limit_but_stops_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = load_frozen_batch_inputs(_repo_root())
    monkeypatch.setattr(paired_batch, "load_frozen_batch_inputs", lambda _root: inputs)
    calls: list[str] = []

    async def terminal_runner(**kwargs: object) -> SimpleNamespace:
        config = cast(PairedRunConfig, kwargs["config"])
        calls.append(config.run_id)
        status = "insufficient_feasible_proposals" if len(calls) == 1 else "completed"
        return SimpleNamespace(status=status)

    monkeypatch.setattr(paired_batch, "run_paired_adaptive", terminal_runner)
    summaries = await run_frozen_agent_matrix(
        _repo_root(), solver_factory=lambda: cast(PairedSolver, _NativeSolver())
    )
    assert len(summaries) == 9
    assert calls == [cell.run_id for cell in FROZEN_AGENT_CELLS]

    calls.clear()

    async def failing_runner(**kwargs: object) -> SimpleNamespace:
        config = cast(PairedRunConfig, kwargs["config"])
        calls.append(config.run_id)
        if len(calls) == 3:
            raise RuntimeError("injected solver failure")
        return SimpleNamespace(status="completed")

    monkeypatch.setattr(paired_batch, "run_paired_adaptive", failing_runner)
    with pytest.raises(RuntimeError, match="injected solver"):
        await run_frozen_agent_matrix(
            _repo_root(), solver_factory=lambda: cast(PairedSolver, _NativeSolver())
        )
    assert calls == [cell.run_id for cell in FROZEN_AGENT_CELLS[:3]]


class _DeterministicInterruptibleSolver:
    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def __call__(
        self,
        _geometry: Geometry,
        state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("injected trace interruption")
        values = [-1.0] * len(frequency_hz)
        values[len(values) // 2] = -10.0 if state == "A" else -9.0
        return SearchCurve(
            solver_name="nec2",
            solver_mode="subprocess",
            frequency_hz=frequency_hz,
            s11_db=tuple(values),
        )


def _normalized_rows(path: Path) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row.pop("timestamp")
    return cast(list[dict[str, object]], rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("cell_index", (0, 3, 6))
async def test_true_agent_resume_matches_uninterrupted_trace(
    tmp_path: Path,
    cell_index: int,
) -> None:
    inputs = load_frozen_batch_inputs(_repo_root())
    cell = FROZEN_AGENT_CELLS[cell_index]
    config = build_agent_run_config(cell, inputs).model_copy(
        update={"run_id": f"trace-{cell.agent}", "evaluation_budget": 3}
    )
    full_root = tmp_path / "full"
    resumed_root = tmp_path / "resumed"
    await run_paired_adaptive(
        config=config,
        proposer=build_agent_proposer(cell, inputs),
        solver=cast(PairedSolver, _DeterministicInterruptibleSolver()),
        runs_root=full_root,
    )
    with pytest.raises(RuntimeError, match="trace interruption"):
        await run_paired_adaptive(
            config=config,
            proposer=build_agent_proposer(cell, inputs),
            solver=cast(PairedSolver, _DeterministicInterruptibleSolver(fail_on_call=3)),
            runs_root=resumed_root,
        )
    await run_paired_adaptive(
        config=config,
        proposer=build_agent_proposer(cell, inputs),
        solver=cast(PairedSolver, _DeterministicInterruptibleSolver()),
        runs_root=resumed_root,
    )
    full_log = full_root / config.run_id / "log.jsonl"
    resumed_log = resumed_root / config.run_id / "log.jsonl"
    assert _normalized_rows(resumed_log) == _normalized_rows(full_log)


@pytest.mark.parametrize(
    "run_id",
    (
        PREFLIGHT_RUN_ID_PREFIX,
        PREFLIGHT_RUN_ID_PREFIX + "-child",
        MANUAL_BASELINE_RUN_ID_PREFIX,
        MANUAL_BASELINE_RUN_ID_PREFIX + "-child",
    ),
)
def test_all_manual_and_preflight_prefixes_remain_excluded(run_id: str) -> None:
    source = load_frozen_batch_inputs(_repo_root()).warm_parent_source
    excluded = source.model_copy(update={"run_id": run_id})
    with pytest.raises(PairedRunError, match="non-agent exclusion"):
        freeze_candidate((cast(PairedEvaluationRecord, excluded),))
