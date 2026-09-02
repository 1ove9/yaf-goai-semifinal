"""Mock-only persistence and selection tests for the paired-state runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    HardwareSpec,
    PairedMeanderError,
    PairedProposal,
    SearchCurve,
    StateControl,
    StateLabel,
    audit_trajectory,
    iter_manual_pairs,
)
from yaf_ai.exploration.paired_runner import (
    PairedRunConfig,
    PairedRunState,
    PairedRunSummary,
    freeze_candidate,
    load_paired_evaluations,
    run_paired_sequence,
)
from yaf_core.domain.geometry import Geometry


class MockNec2Solver:
    """Deterministic async solver replacement that records every requested band."""

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[tuple[StateLabel, tuple[float, ...]]] = []
        self.fail_on_call = fail_on_call

    async def __call__(
        self,
        _geometry: Geometry,
        state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        self.calls.append((state, frequency_hz))
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("injected interruption")
        values = [-0.2] * len(frequency_hz)
        values[50] = -8.0 if state == "A" else -7.0
        return SearchCurve(
            solver_name="nec2",
            solver_mode="subprocess",
            frequency_hz=frequency_hz,
            s11_db=tuple(values),
            realized_gain_dbi=tuple(2.0 for _ in frequency_hz),
        )


def _legal_proposals(count: int, proposer: str = "test") -> tuple[PairedProposal, ...]:
    selected: list[PairedProposal] = []
    for _hardware_index, _pair_index, proposal in iter_manual_pairs():
        proposal = proposal.model_copy(update={"proposer": proposer})
        if audit_trajectory(proposal).valid:
            selected.append(proposal)
            if len(selected) == count:
                return tuple(selected)
    raise AssertionError("manual grid did not contain enough legal proposals")


def _invalid_proposal() -> PairedProposal:
    return PairedProposal(
        hardware=HardwareSpec(
            turn_count=6,
            feed_gap_ratio_ppm=20_000,
            terminal_ratio_ppm=1_000_000,
        ),
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
        proposer="invalid",
    )


def _config(
    run_id: str,
    agent: Literal["random", "es-cold", "es-warm", "manual"] = "random",
    *,
    anchor_released: bool = True,
) -> PairedRunConfig:
    warm = agent == "es-warm"
    return PairedRunConfig(
        run_id=run_id,
        agent=agent,
        seed=101,
        evaluation_budget=2,
        anchor_released=anchor_released,
        openems_cross_check_authorized=False,
        preregistration_commit="7f4e01f",
        manual_baseline_commit="manual123" if warm else None,
        warm_parent_run_id="manual-baseline" if warm else None,
        warm_parent_pair_hash="a" * 64 if warm else None,
        warm_parent_document_sha256="b" * 64 if warm else None,
        warm_parent_hardware_hash="c" * 64 if warm else None,
        warm_parent_state_a_geometry_hash="d" * 64 if warm else None,
        warm_parent_state_b_geometry_hash="e" * 64 if warm else None,
        warm_parent_step_index=1 if warm else None,
        warm_parent_hardware_grid_index=2 if warm else None,
        warm_parent_pair_grid_index=3 if warm else None,
        warm_parent_search_score=0.5 if warm else None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("agent", ("random", "es-cold", "es-warm"))
async def test_three_arms_each_run_two_mock_pairs_with_exact_bands(
    tmp_path: Path,
    agent: Literal["random", "es-cold", "es-warm"],
) -> None:
    solver = MockNec2Solver()
    run_id = f"semifinal-{agent}"
    summary = await run_paired_sequence(
        config=_config(run_id, agent),
        proposals=_legal_proposals(2, agent),
        solver=solver,
        runs_root=tmp_path,
    )
    assert summary.status == "completed"
    assert summary.steps_completed == 2
    assert summary.solver_mode_counts == {"subprocess": 4}
    assert solver.calls == [
        ("A", STATE_A_FREQUENCIES_HZ),
        ("B", STATE_B_FREQUENCIES_HZ),
        ("A", STATE_A_FREQUENCIES_HZ),
        ("B", STATE_B_FREQUENCIES_HZ),
    ]
    records = load_paired_evaluations(tmp_path / run_id / "log.jsonl")
    assert len(records) == 2
    assert all(record.evaluation.metrics.valid_pair_search for record in records)


@pytest.mark.asyncio
async def test_interrupted_run_resumes_without_duplicate_accepted_rows(
    tmp_path: Path,
) -> None:
    config = _config("resume-test")
    proposals = _legal_proposals(2)
    interrupted = MockNec2Solver(fail_on_call=3)
    with pytest.raises(RuntimeError, match="injected interruption"):
        await run_paired_sequence(
            config=config,
            proposals=proposals,
            solver=interrupted,
            runs_root=tmp_path,
        )
    state = PairedRunState.model_validate_json(
        (tmp_path / config.run_id / "state.json").read_text(encoding="utf-8")
    )
    assert state.evaluations_completed == 1
    assert state.next_proposal_index == 1
    assert len(load_paired_evaluations(tmp_path / config.run_id / "log.jsonl")) == 1

    resumed = MockNec2Solver()
    summary = await run_paired_sequence(
        config=config,
        proposals=proposals,
        solver=resumed,
        runs_root=tmp_path,
    )
    assert summary.status == "completed"
    assert summary.steps_completed == 2
    assert resumed.calls == [
        ("A", STATE_A_FREQUENCIES_HZ),
        ("B", STATE_B_FREQUENCIES_HZ),
    ]
    assert len(load_paired_evaluations(tmp_path / config.run_id / "log.jsonl")) == 2


@pytest.mark.asyncio
async def test_completed_run_is_idempotent_and_all_files_are_lf_only(
    tmp_path: Path,
) -> None:
    config = _config("idempotent-test")
    solver = MockNec2Solver()
    proposals = _legal_proposals(2)
    first = await run_paired_sequence(
        config=config,
        proposals=proposals,
        solver=solver,
        runs_root=tmp_path,
    )
    second = await run_paired_sequence(
        config=config,
        proposals=tuple(reversed(proposals)),
        solver=solver,
        runs_root=tmp_path,
    )
    assert first == second
    assert len(solver.calls) == 4
    for name in ("log.jsonl", "state.json", "summary.json"):
        payload = (tmp_path / config.run_id / name).read_bytes()
        assert b"\r" not in payload


@pytest.mark.asyncio
async def test_rejection_is_logged_and_consumes_zero_pair_budget(
    tmp_path: Path,
) -> None:
    config = _config("rejection-test").model_copy(update={"evaluation_budget": 1})
    solver = MockNec2Solver()
    summary = await run_paired_sequence(
        config=config,
        proposals=(_invalid_proposal(), _legal_proposals(1)[0]),
        solver=solver,
        runs_root=tmp_path,
    )
    assert summary.status == "completed"
    assert summary.steps_completed == 1
    assert summary.rejected_proposals == 1
    assert summary.proposal_attempts == 2
    assert len(solver.calls) == 2
    rows = [
        json.loads(line)
        for line in (tmp_path / config.run_id / "log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["event_type"] for row in rows] == [
        "paired_rejection",
        "paired_evaluation",
    ]
    assert rows[0]["budget_remaining"] == 1


@pytest.mark.asyncio
async def test_unreleased_anchor_records_fact_but_allows_nec2_run(
    tmp_path: Path,
) -> None:
    config = _config("anchor-blocked", anchor_released=False)
    solver = MockNec2Solver()
    summary = await run_paired_sequence(
        config=config,
        proposals=_legal_proposals(2),
        solver=solver,
        runs_root=tmp_path,
    )
    persisted = PairedRunSummary.model_validate_json(
        (tmp_path / config.run_id / "summary.json").read_text(encoding="utf-8")
    )
    assert summary == persisted
    assert summary.status == "completed"
    assert summary.steps_completed == 2
    assert summary.verdict_ceiling == "insufficient_evidence"
    assert len(solver.calls) == 4


def test_warm_arm_requires_complete_committed_parent_provenance() -> None:
    with pytest.raises(ValidationError, match="committed manual-parent"):
        PairedRunConfig(
            run_id="bad-warm",
            agent="es-warm",
            seed=101,
            evaluation_budget=2,
            anchor_released=True,
            openems_cross_check_authorized=False,
            preregistration_commit="7f4e01f",
        )
    with pytest.raises(ValidationError, match="only es-warm"):
        PairedRunConfig(
            run_id="bad-random",
            agent="random",
            seed=101,
            evaluation_budget=2,
            anchor_released=True,
            openems_cross_check_authorized=False,
            preregistration_commit="7f4e01f",
            manual_baseline_commit="manual123",
        )


@pytest.mark.asyncio
async def test_candidate_freeze_uses_valid_pool_then_frozen_tie_breaks(
    tmp_path: Path,
) -> None:
    config = _config("candidate-test")
    await run_paired_sequence(
        config=config,
        proposals=_legal_proposals(2),
        solver=MockNec2Solver(),
        runs_root=tmp_path,
    )
    records = list(load_paired_evaluations(tmp_path / config.run_id / "log.jsonl"))
    first_metrics = records[0].evaluation.metrics.model_copy(
        update={"valid_pair_search": False, "base_score": 0.999}
    )
    records[0] = records[0].model_copy(
        update={"evaluation": records[0].evaluation.model_copy(update={"metrics": first_metrics})}
    )
    candidate = freeze_candidate(records)
    assert candidate.step_index == 1
    assert candidate.positive_eligible
    assert candidate.valid_pair_search

    tied_metrics = records[1].evaluation.metrics.model_copy(update={"base_score": 0.8})
    first = records[1].model_copy(
        update={
            "run_id": "z-run",
            "step_index": 5,
            "evaluation": records[1].evaluation.model_copy(
                update={
                    "hardware_hash": "b" * 64,
                    "metrics": tied_metrics,
                }
            ),
        }
    )
    second = records[1].model_copy(
        update={
            "run_id": "a-run",
            "step_index": 9,
            "evaluation": records[1].evaluation.model_copy(
                update={
                    "hardware_hash": "a" * 64,
                    "metrics": tied_metrics,
                }
            ),
        }
    )
    assert freeze_candidate((first, second)).hardware_hash == "a" * 64


@pytest.mark.asyncio
async def test_openems_curve_cannot_enter_selection_log(
    tmp_path: Path,
) -> None:
    async def bad_solver(
        _geometry: Geometry,
        state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        values = [-0.1] * len(frequency_hz)
        values[50] = -8.0
        return SearchCurve(
            solver_name="openems",
            solver_mode="subprocess",
            frequency_hz=frequency_hz,
            s11_db=tuple(values),
        )

    config = _config("openems-leak").model_copy(update={"evaluation_budget": 1})
    with pytest.raises(PairedMeanderError, match="NEC2 only"):
        await run_paired_sequence(
            config=config,
            proposals=_legal_proposals(1),
            solver=bad_solver,
            runs_root=tmp_path,
        )
    assert load_paired_evaluations(tmp_path / config.run_id / "log.jsonl") == ()
