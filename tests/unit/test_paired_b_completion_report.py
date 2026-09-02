"""Tests for the B-parent conditional-completion report CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts import paired_b_completion_report as cli
from yaf_ai.analysis.paired_b_completion import (
    MAPPING_VERSION,
    SPEC_REVISION,
    STUDY_ID,
    expected_run_id,
)
from yaf_ai.exploration.paired_b_completion_coordinates import (
    P01,
    decode_a_only_coordinates,
)
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    SearchCurve,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRunSummary,
    _evaluation,
)


def _curve(frequencies: tuple[float, ...]) -> SearchCurve:
    s11_db = [-0.1] * len(frequencies)
    s11_db[len(frequencies) // 2] = -8.0
    return SearchCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=frequencies,
        s11_db=tuple(s11_db),
        realized_gain_dbi=None,
    )


def _config(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "agent": "random-b-completion",
        "seed": 101,
        "evaluation_budget": 300,
        "study_id": STUDY_ID,
        "spec_revision": SPEC_REVISION,
        "mapping_version": MAPPING_VERSION,
        "parent_id": "p01",
        "parent_code": 1,
        "agent_code": 3,
        "anchor_released": False,
        "openems_cross_check_authorized": False,
        "rng_version": "numpy-pcg64-seedsequence-v1",
        "stream_format_version": "canonical-json-float-hex-lf-v1",
        "rng_stream_revision": 1,
        "max_consecutive_rejections": 100,
        "max_total_proposal_attempts": 300,
    }


def _write_completed_run(root: Path) -> tuple[Path, dict[str, Any]]:
    run_id = expected_run_id("p01", "random-b-completion", 101)
    run_directory = root / "runs" / run_id
    run_directory.mkdir(parents=True)
    proposal = decode_a_only_coordinates(
        P01,
        (0.5, 0.5),
        "random-b-completion",
    )
    evaluation = _evaluation(
        proposal,
        _curve(STATE_A_FREQUENCIES_HZ),
        _curve(STATE_B_FREQUENCIES_HZ),
    )
    timestamp = datetime(2026, 8, 31, tzinfo=UTC)
    records = tuple(
        PairedEvaluationRecord(
            run_id=run_id,
            step_index=index,
            proposal_index=index,
            timestamp=timestamp,
            proposer="random-b-completion",
            proposal=proposal,
            evaluation=evaluation,
        )
        for index in range(300)
    )
    log_payload = "".join(
        json.dumps(
            record.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
        for record in records
    ).encode("utf-8")
    (run_directory / "log.jsonl").write_bytes(log_payload)

    config = _config(run_id)
    summary = PairedRunSummary(
        run_id=run_id,
        started_at=timestamp,
        finished_at=timestamp,
        seed=101,
        config_hash=cli._canonical_config_hash(config),
        config=config,
        steps_completed=300,
        evaluation_budget=300,
        solver_mode_counts={"subprocess": 600},
        rejected_proposals=0,
        proposal_attempts=300,
        status="completed",
        termination_reason="accepted paired-evaluation budget completed",
    )
    summary_payload = (
        json.dumps(
            summary.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    (run_directory / "summary.json").write_bytes(summary_payload)
    return run_directory, config


def test_completed_cell_replays_300_records_and_recomputes_hypotheses(
    tmp_path: Path,
) -> None:
    _write_completed_run(tmp_path)
    row, records = cli._load_completed_cell(
        tmp_path / "runs",
        "p01",
        "random-b-completion",
        101,
    )
    assert row.execution_status == "completed"
    assert row.accepted_count == 300
    assert row.rejected_count == 0
    assert row.proposal_attempts == 300
    assert row.solver_mode_counts == {"subprocess": 600}
    assert row.h1_count == 300
    assert row.h2_count == 300
    assert len(records) == 300


def test_completed_cell_rejects_changed_study_config(tmp_path: Path) -> None:
    run_directory, config = _write_completed_run(tmp_path)
    summary_path = run_directory / "summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    config["study_id"] = "changed-study"
    payload["config"] = config
    payload["config_hash"] = cli._canonical_config_hash(config)
    summary_path.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    with pytest.raises(ValueError, match="config fields changed"):
        cli._load_completed_cell(
            tmp_path / "runs",
            "p01",
            "random-b-completion",
            101,
        )


def _write_failure(root: Path) -> Path:
    path = root / "matrix_failure.json"
    path.write_bytes(
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "study_id": STUDY_ID,
                    "study_status": "solver_timeout",
                    "failed_run_id": expected_run_id(
                        "p01",
                        "random-b-completion",
                        101,
                    ),
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "proposal_attempts": 1,
                    "partial_log_sha256": cli.EMPTY_SHA256,
                    "partial_log_bytes": 0,
                    "partial_log_lines": 0,
                    "exception_class": "TimeoutError",
                    "exception_message": "frozen solver timeout",
                    "expected_b_hashes": None,
                    "actual_b_hashes": None,
                    "completed_prefix": [],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    return path


def test_failure_json_produces_null_endpoint_and_lf_only_cli_outputs(
    tmp_path: Path,
) -> None:
    failure_path = _write_failure(tmp_path)
    appendix = cli.load_b_completion_evidence(tmp_path, failure_path)
    assert appendix.study_status == "solver_timeout"
    assert appendix.failed_run_id == expected_run_id(
        "p01",
        "random-b-completion",
        101,
    )
    assert appendix.scientific_endpoint is None
    assert appendix.selected_hypothesis is None
    assert len(appendix.rows) == 20

    assert (
        cli.main(
            [
                "--repo-root",
                str(tmp_path),
                "--failure-json",
                str(failure_path),
            ]
        )
        == 1
    )
    for name in ("appendix.json", "report.md"):
        payload = (tmp_path / cli.OUTPUT_DIRECTORY / name).read_bytes()
        assert b"\r" not in payload
        assert payload.endswith(b"\n")


def test_success_cli_uses_fixed_output_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    appendix = SimpleNamespace(study_status="complete", rows=())
    written: list[Path] = []
    monkeypatch.setattr(
        cli,
        "load_b_completion_evidence",
        lambda *_args: appendix,
    )
    monkeypatch.setattr(
        cli,
        "write_b_completion_outputs",
        lambda path, _appendix: written.append(path),
    )
    assert cli.main(["--repo-root", str(tmp_path)]) == 0
    assert written == [tmp_path.resolve() / cli.OUTPUT_DIRECTORY]
