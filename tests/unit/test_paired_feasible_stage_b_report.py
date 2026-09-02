"""CLI tests for the evidence-gated exact-v2 Stage-B report."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import paired_feasible_stage_b_report as cli


def test_gate_failure_happens_before_loader_or_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_gate(root: Path, commit: str) -> object:
        del root, commit
        raise ValueError("gate blocked")

    monkeypatch.setattr(cli, "load_stage_b_inputs", fail_gate)
    monkeypatch.setattr(
        cli,
        "load_stage_b_evidence",
        lambda *_args: pytest.fail("loader ran before gate passed"),
    )
    monkeypatch.setattr(
        cli,
        "write_stage_b_outputs",
        lambda *_args: pytest.fail("output was written before gate passed"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "paired_feasible_stage_b_report.py",
            "--repo-root",
            str(tmp_path),
            "--stage-a-evidence-commit",
            "a" * 40,
        ],
    )
    with pytest.raises(ValueError, match="gate blocked"):
        cli.main()


@pytest.mark.parametrize(
    ("status", "expected"),
    [("complete", 0), ("study_incomplete", 1)],
)
def test_cli_uses_fixed_output_for_complete_and_failed_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str,
    expected: int,
) -> None:
    written: list[Path] = []
    appendix = SimpleNamespace(study_status=status, rows=())
    monkeypatch.setattr(cli, "load_stage_b_inputs", lambda *_args: object())
    monkeypatch.setattr(cli, "load_stage_b_evidence", lambda *_args: appendix)
    monkeypatch.setattr(
        cli,
        "write_stage_b_outputs",
        lambda path, _appendix: written.append(path),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "paired_feasible_stage_b_report.py",
            "--repo-root",
            str(tmp_path),
            "--stage-a-evidence-commit",
            "a" * 40,
        ],
    )
    assert cli.main() == expected
    assert written == [tmp_path.resolve() / cli.OUTPUT_DIRECTORY]
