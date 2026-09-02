"""Tests for B-parent completion provenance and source-integrity gates."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from yaf_ai.exploration import paired_b_completion_gates as gates
from yaf_ai.exploration.paired_feasible_gates import StageAGateError
from yaf_ai.exploration.paired_meander import STATE_B_FREQUENCIES_HZ


def _git(root: Path, *arguments: str) -> str:
    process = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return process.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "--all")
    _git(root, "-c", "user.name=Gate Test", "-c", "user.email=gate@test", "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _curve(*, valid: bool) -> dict[str, object]:
    values = [-0.1] * len(STATE_B_FREQUENCIES_HZ)
    values[50 if valid else 0] = -8.0
    return {
        "solver_name": "nec2",
        "solver_mode": "subprocess",
        "frequency_hz": list(STATE_B_FREQUENCIES_HZ),
        "s11_db": values,
        "realized_gain_dbi": None,
    }


def _event(*, run_id: str, index: int, valid: bool) -> dict[str, object]:
    curve = _curve(valid=valid)
    return {
        "event_type": "paired_evaluation",
        "run_id": run_id,
        "step_index": index,
        "proposal_index": index,
        "proposal": {
            "hardware": {
                "turn_count": 3,
                "feed_gap_ratio_ppm": 49_001,
                "terminal_ratio_ppm": 0,
            },
            "state_b": {
                "total_wire_length_um": 26_090,
                "span_ratio_ppm": 785_552,
            },
        },
        "evaluation": {
            "pair_hash": hashlib.sha256(f"pair-{index}".encode()).hexdigest(),
            "hardware_hash": hashlib.sha256(b"hardware").hexdigest(),
            "state_b_geometry_hash": hashlib.sha256(b"geometry").hexdigest(),
            "state_b_curve": curve,
            "metrics": {"state_b": {"valid_search": valid}},
        },
    }


def test_canonical_curve_hash_is_order_independent_and_rejects_nan() -> None:
    first = {"b": [2.0], "a": 1.0}
    second = {"a": 1.0, "b": [2.0]}
    assert gates.canonical_curve_sha256(first) == gates.canonical_curve_sha256(second)
    with pytest.raises(StageAGateError, match="canonicalize"):
        gates.canonical_curve_sha256({"value": float("nan")})


def test_recomputed_validity_uses_curve_and_rejects_logged_drift() -> None:
    event = _event(run_id="run", index=0, valid=True)
    valid, payload = gates._recomputed_b_valid(event, "fixture")
    assert valid
    assert payload == event["evaluation"]["state_b_curve"]  # type: ignore[index]
    event["evaluation"]["metrics"]["state_b"]["valid_search"] = False  # type: ignore[index]
    with pytest.raises(StageAGateError, match="validity differs"):
        gates._recomputed_b_valid(event, "fixture")


def test_stage_b_source_requires_exactly_two_curve_derived_parents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_ids = ("run-a", "run-b")
    monkeypatch.setattr(gates, "STAGE_B_RUN_IDS", run_ids)
    monkeypatch.setattr(gates, "STAGE_B_RUN_PREFIX", "run-")
    entries: list[dict[str, object]] = []
    for run_number, run_id in enumerate(run_ids):
        run_dir = tmp_path / "artifacts" / "runs" / run_id
        run_dir.mkdir(parents=True)
        lines = []
        for index in range(600):
            event = _event(
                run_id=run_id,
                index=index,
                valid=(index == 10 and run_number == 0) or (index == 20 and run_number == 1),
            )
            lines.append(
                json.dumps(event, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            )
        log = b"".join(lines)
        summary = json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "steps_completed": 600,
                "evaluation_budget": 600,
                "rejected_proposals": 0,
                "proposal_attempts": 600,
                "solver_mode_counts": {"subprocess": 1200},
                "config_hash": f"config-{run_id}",
            },
            separators=(",", ":"),
        ).encode()
        (run_dir / "log.jsonl").write_bytes(log)
        (run_dir / "summary.json").write_bytes(summary)
        entries.append(
            {
                "run_id": run_id,
                "overwritten": False,
                "config_hash": f"config-{run_id}",
                "sha256": {
                    "log.jsonl": hashlib.sha256(log).hexdigest(),
                    "summary.json": hashlib.sha256(summary).hexdigest(),
                },
            }
        )

    monkeypatch.setattr(
        gates,
        "_git_blob",
        lambda root, commit, path: (root / path).read_bytes(),
    )
    monkeypatch.setattr(
        gates,
        "FROZEN_PARENTS",
        tuple(
            gates._parent_from_event(
                _event(run_id=run_id, index=index, valid=True),
                (
                    json.dumps(
                        _event(run_id=run_id, index=index, valid=True),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                    + b"\n"
                ),
                _curve(valid=True),
                "p01" if position == 0 else "p02",
                "fixture",
            )
            for position, (run_id, index) in enumerate((("run-a", 10), ("run-b", 20)))
        ),
    )
    parents, accepted = gates._validate_stage_b_source(tmp_path, "commit", entries)
    assert accepted == 1200
    assert parents == gates.FROZEN_PARENTS

    entries[0]["overwritten"] = True
    with pytest.raises(StageAGateError, match="overwritten"):
        gates._validate_stage_b_source(tmp_path, "commit", entries)
    entries[0]["overwritten"] = False

    log_path = tmp_path / "artifacts" / "runs" / "run-b" / "log.jsonl"
    payload = log_path.read_bytes().replace(b'"valid_search":false', b'"valid_search":true', 1)
    log_path.write_bytes(payload)
    entries[1]["sha256"]["log.jsonl"] = hashlib.sha256(payload).hexdigest()  # type: ignore[index]
    with pytest.raises(StageAGateError, match="validity differs"):
        gates._validate_stage_b_source(tmp_path, "commit", entries)


def test_runtime_blob_gate_requires_implementation_execution_workspace_identity(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    runtime = tmp_path / "runtime.py"
    runtime.write_text("VALUE = 1\n", encoding="utf-8")
    implementation = _commit(tmp_path, "implementation")
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("evidence\n", encoding="utf-8")
    execution = _commit(tmp_path, "evidence")
    result = gates.validate_runtime_path_blobs(
        tmp_path, implementation, execution, (Path("runtime.py"),)
    )
    assert result["runtime.py"] == _git(tmp_path, "rev-parse", f"{implementation}:runtime.py")

    runtime.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(StageAGateError, match="runtime path bytes changed"):
        gates.validate_runtime_path_blobs(
            tmp_path, implementation, execution, (Path("runtime.py"),)
        )


def test_runtime_blob_gate_rejects_duplicate_and_escaping_paths(tmp_path: Path) -> None:
    full = "a" * 40
    with pytest.raises(StageAGateError, match="repository-relative"):
        gates.validate_runtime_path_blobs(
            tmp_path, full, full, (Path("../outside.py"),)
        )


def test_frozen_constants_match_preregistration() -> None:
    assert gates.SOURCE_EVIDENCE_COMMIT == "8fb865005791a3f1fa53d212d0f0a1e813f19558"
    assert gates.PREREGISTRATION_COMMIT == "9e9edbc762e8c885052aa08d469e6872b719d79e"
    assert len(gates.FROZEN_SCIENCE_BLOBS) == 12
    assert tuple(parent.parent_id for parent in gates.FROZEN_PARENTS) == ("p01", "p02")
