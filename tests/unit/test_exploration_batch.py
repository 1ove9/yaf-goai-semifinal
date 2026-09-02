"""Tests for recoverable exploration batch execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from yaf_ai.exploration.batch import (
    BatchRunRecord,
    RunExecution,
    load_batch_config,
    run_batch,
)


@pytest.mark.asyncio
async def test_completed_runs_are_skipped_on_resume(tmp_path: Path) -> None:
    calls: list[str] = []
    completed_hooks: list[str] = []

    async def mock_solver_run(
        record: BatchRunRecord,
        _runs_root: Path,
    ) -> RunExecution:
        calls.append(record.run_key)
        return RunExecution(duration_seconds=0.1, steps_completed=record.budget)

    state = await run_batch(
        "resume-test",
        repo_root=tmp_path,
        executor=mock_solver_run,
        spec_names=("wifi24",),
        duration_limit_seconds=10.0,
        choices=((2, (101,)),),
        on_completed=lambda record: completed_hooks.append(record.run_key),
    )

    assert len(calls) == 3
    assert completed_hooks == calls
    assert all(record.status == "completed" for record in state.runs)
    config_path = tmp_path / "runs" / "batch_resume-test" / "config.json"
    assert load_batch_config(config_path).config.budget == 2
    assert b"\r" not in config_path.read_bytes()

    async def unexpected_run(
        _record: BatchRunRecord,
        _runs_root: Path,
    ) -> RunExecution:
        raise AssertionError("completed run was executed again")

    resumed = await run_batch(
        "resume-test",
        repo_root=tmp_path,
        executor=unexpected_run,
        spec_names=("wifi24",),
        duration_limit_seconds=10.0,
        choices=((2, (101,)),),
        on_completed=lambda record: completed_hooks.append(record.run_key),
    )
    assert resumed == state
    assert completed_hooks == calls + calls


@pytest.mark.asyncio
async def test_one_failed_run_does_not_stop_remaining_matrix(tmp_path: Path) -> None:
    calls: list[str] = []

    async def intermittently_failing_solver(
        record: BatchRunRecord,
        _runs_root: Path,
    ) -> RunExecution:
        calls.append(record.run_key)
        if record.agent == "gp":
            raise RuntimeError("synthetic solver failure")
        return RunExecution(duration_seconds=0.1, steps_completed=record.budget)

    state = await run_batch(
        "failure-test",
        repo_root=tmp_path,
        executor=intermittently_failing_solver,
        spec_names=("wifi24",),
        duration_limit_seconds=10.0,
        choices=((2, (101,)),),
    )

    by_agent = {record.agent: record for record in state.runs}
    assert by_agent["gp"].status == "failed"
    assert by_agent["gp"].error == "RuntimeError: synthetic solver failure"
    assert by_agent["random"].status == "completed"
    assert calls == [
        "wifi24:classic:0",
        "wifi24:gp:101",
        "wifi24:random:101",
    ]
