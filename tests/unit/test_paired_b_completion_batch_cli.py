from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from yaf_ai.exploration.paired_b_completion_batch import (
    MATRIX_FAILURE_PATH,
    BCompletionCellResult,
    BCompletionMatrixError,
    MatrixFailureRecord,
)


def _load_cli() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "paired_b_completion_batch.py"
    spec = importlib.util.spec_from_file_location("paired_b_completion_batch_cli", path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load paired B-completion batch CLI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_passes_both_commits_and_prints_each_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli()
    observed: dict[str, object] = {}

    async def fake_matrix(
        repo_root: Path,
        *,
        implementation_commit: str,
        certificate_evidence_commit: str,
    ) -> tuple[BCompletionCellResult, ...]:
        observed.update(
            repo_root=repo_root,
            implementation_commit=implementation_commit,
            certificate_evidence_commit=certificate_evidence_commit,
        )
        first = SimpleNamespace(
            summary=SimpleNamespace(run_id="run-1", status="completed", steps_completed=300)
        )
        second = SimpleNamespace(
            summary=SimpleNamespace(run_id="run-2", status="completed", steps_completed=300)
        )
        return cast(tuple[BCompletionCellResult, ...], (first, second))

    monkeypatch.setattr(cli, "run_b_completion_matrix", fake_matrix)
    result = cli.main(
        [
            "--implementation-commit",
            "a" * 40,
            "--certificate-evidence-commit",
            "b" * 40,
        ]
    )
    output = capsys.readouterr()
    assert result == 0
    assert observed["implementation_commit"] == "a" * 40
    assert observed["certificate_evidence_commit"] == "b" * 40
    assert "run-1: status=completed; steps=300" in output.out
    assert "run-2: status=completed; steps=300" in output.out
    assert output.err == ""


def test_cli_prints_terminal_marker_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load_cli()
    failure = MatrixFailureRecord(
        study_status="state_b_reproduction_failed",
        failed_run_id="semifinal-paired-b-completion-p01-random-s101",
        accepted_count=17,
        rejected_count=0,
        proposal_attempts=17,
        partial_log_sha256="1" * 64,
        partial_log_bytes=1234,
        partial_log_lines=17,
        exception_class="BCompletionStateBReproductionError",
        exception_message="state-B curve changed",
        expected_b_hashes={"state_b_curve_sha256": "2" * 64},
        actual_b_hashes={"state_b_curve_sha256": "3" * 64},
        completed_prefix=(),
    )

    async def fail_matrix(*_args: object, **_kwargs: object) -> tuple[()]:
        raise BCompletionMatrixError(failure)

    monkeypatch.setattr(cli, "run_b_completion_matrix", fail_matrix)
    result = cli.main(
        [
            "--implementation-commit",
            "a" * 40,
            "--certificate-evidence-commit",
            "b" * 40,
        ]
    )
    output = capsys.readouterr()
    assert result == 1
    assert output.out == ""
    prefix, payload = output.err.strip().split(" ", 1)
    assert prefix == f"terminal_marker={MATRIX_FAILURE_PATH.as_posix()}"
    marker = json.loads(payload)
    assert marker["study_status"] == "state_b_reproduction_failed"
    assert marker["failed_run_id"] == failure.failed_run_id
    assert marker["accepted_count"] == 17


def test_cli_source_contains_no_archive_or_analysis_dispatch() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "paired_b_completion_batch.py"
    ).read_text(encoding="utf-8")
    assert "archive_run" not in source
    assert "paired_b_completion_report" not in source
