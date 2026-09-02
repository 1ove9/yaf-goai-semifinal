"""Tests for the solver-free paired-feasibility Stage A."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from yaf_ai.analysis.paired_feasible_stage_a import (
    CONDITIONAL_REPRESENTATION,
    LEGACY_REPRESENTATION,
    SEEDS,
    STREAM_FORMAT_VERSION,
    TURNS,
    StageAInvariantError,
    _canonical_json_line,
    _exact_nominal_rejection,
    _legacy_decode,
    _run_cell,
    _status,
    build_stage_a_summary,
    write_stage_a_outputs,
)
from yaf_ai.exploration.paired_meander import (
    HardwareSpec,
    PairedProposal,
    StateControl,
)


def test_canonical_stream_uses_float_hex_and_lf() -> None:
    line = _canonical_json_line({"draw_index": 0, "z": [0.5.hex()]})
    assert line == b'{"draw_index":0,"z":["0x1.0000000000000p-1"]}\n'
    assert b"\r" not in line


def test_stage_a_has_turn_major_shared_deterministic_streams() -> None:
    first = build_stage_a_summary(raw_draws=3)
    second = build_stage_a_summary(raw_draws=3)
    assert [(cell.turn, cell.seed) for cell in first.cells] == [
        (turn, seed) for turn in TURNS for seed in SEEDS
    ]
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.stream_format_version == STREAM_FORMAT_VERSION
    assert first.study_id == "semifinal-paired-feasibility-stratified-exact-v2"
    assert first.spec_revision == "2.0-exact-nominal-support"
    assert first.mapping_version == "conditional-exact-feasible-turn-v2"
    assert len(first.boundary_witnesses) == 24
    assert all(cell.conditional.valid == 3 for cell in first.cells)
    assert all(cell.conditional.trajectory_infeasible == 0 for cell in first.cells)


def test_raw_digest_matches_frozen_pcg64_line_stream() -> None:
    summary = build_stage_a_summary(raw_draws=1)
    cell = summary.cells[0]
    import numpy as np

    generator = np.random.Generator(
        np.random.PCG64(np.random.SeedSequence([101, 0, 3, 1]))
    )
    values = generator.random(6).tolist()
    expected = _canonical_json_line(
        {"draw_index": 0, "z": [float(value).hex() for value in values]}
    )
    assert cell.raw_stream_sha256 == hashlib.sha256(expected).hexdigest()
    assert cell.legacy.representation == LEGACY_REPRESENTATION
    assert cell.conditional.representation == CONDITIONAL_REPRESENTATION


def test_conditional_infeasibility_aborts_without_endpoint() -> None:
    def invalid(turn: int, values: list[float]) -> PairedProposal:
        proposal = _legacy_decode(turn, values)
        return proposal.model_copy(
            update={
                "state_a": StateControl(
                    state="A", total_wire_length_um=50_000, span_ratio_ppm=760_000
                ),
                "state_b": StateControl(
                    state="B", total_wire_length_um=22_000, span_ratio_ppm=760_000
                ),
            }
        )

    with pytest.raises(StageAInvariantError, match="conditional .*invariant failed"):
        _run_cell(
            3,
            101,
            raw_draws=1,
            conditional_decoder=invalid,
        )


def test_reduced_matrix_cannot_persist_as_completed(tmp_path: Path) -> None:
    summary = build_stage_a_summary(raw_draws=2)
    with pytest.raises(StageAInvariantError, match="validated Stage-A provenance"):
        write_stage_a_outputs(tmp_path, summary)
    assert not list(tmp_path.iterdir())


def test_endpoint_classification_uses_four_of_five_seed_rule() -> None:
    summary = build_stage_a_summary(raw_draws=1)
    improved = sum(item.reproducibly_improved for item in summary.turn_coverage)
    assert summary.reproducibly_improved_turn_count == improved
    assert summary.representation_endpoint in {
        "coverage_improved_all_turns",
        "coverage_improved_some_turns",
        "coverage_improvement_not_observed",
    }


def test_summary_rejects_tampered_cell_and_aggregate_fields() -> None:
    summary = build_stage_a_summary(raw_draws=1)
    payload = summary.model_dump(mode="json")
    payload["cells"][0]["coverage_pass"] = not payload["cells"][0]["coverage_pass"]
    with pytest.raises(ValueError, match="coverage invariant"):
        type(summary).model_validate(payload)

    payload = summary.model_dump(mode="json")
    payload["representation_endpoint"] = (
        "coverage_improvement_not_observed"
        if summary.representation_endpoint != "coverage_improvement_not_observed"
        else "coverage_improved_all_turns"
    )
    with pytest.raises(ValueError, match="aggregate endpoint"):
        type(summary).model_validate(payload)


def test_summary_rejects_tampered_stream_and_boundary_evidence() -> None:
    summary = build_stage_a_summary(raw_draws=1)
    payload = summary.model_dump(mode="json")
    payload["cells"][0]["raw_stream_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="stream evidence"):
        type(summary).model_validate(payload)

    payload = summary.model_dump(mode="json")
    payload["cells"][0]["legacy"]["status_sha256"] = "1" * 64
    with pytest.raises(ValueError, match="stream evidence"):
        type(summary).model_validate(payload)

    payload = summary.model_dump(mode="json")
    payload["boundary_witnesses"][0]["z"] = [0.5.hex()] * 6
    with pytest.raises(ValueError, match="boundary witness"):
        type(summary).model_validate(payload)

    payload = summary.model_dump(mode="json")
    payload["boundary_witnesses"][0]["proposal"] = payload[
        "boundary_witnesses"
    ][1]["proposal"]
    with pytest.raises(ValueError, match="boundary witness"):
        type(summary).model_validate(payload)

def test_workspace_tamper_gate_rejects_before_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yaf_ai.exploration import paired_feasible_gates as gates

    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"tampered")
    monkeypatch.setattr(gates, "_git_blob", lambda *_args: b"committed")
    with pytest.raises(gates.StageAGateError, match="differs from committed"):
        gates._workspace_exact(
            tmp_path,
            "0" * 40,
            Path("evidence.json"),
            hashlib.sha256(b"committed").hexdigest(),
            "test evidence",
        )
    assert not (tmp_path / "summary.json").exists()


def test_ancestor_gate_rejects_nonancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from subprocess import CompletedProcess

    from yaf_ai.exploration import paired_feasible_gates as gates

    monkeypatch.setattr(
        gates.subprocess,
        "run",
        lambda *_args, **_kwargs: CompletedProcess([], 1, b"", b""),
    )
    with pytest.raises(gates.StageAGateError, match="is not an ancestor"):
        gates._require_ancestor(tmp_path, "1" * 40, "2" * 40)


def test_dirty_code_tree_gate_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yaf_ai.exploration import paired_feasible_gates as gates

    monkeypatch.setattr(gates, "_git", lambda *_args: b" M yaf_ai/module.py\n")
    with pytest.raises(gates.StageAGateError, match="code tree is not clean"):
        gates._validate_clean_code_tree(tmp_path)


def test_cli_gate_failure_precedes_computation_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from scripts import paired_feasible_stage_a as command
    from yaf_ai.exploration.paired_feasible_gates import StageAGateError

    output = tmp_path / command.DEFAULT_OUTPUT
    computed = False

    def fail_gate(_root: Path) -> None:
        raise StageAGateError("forced gate failure")

    def forbidden_run(*_args: object, **_kwargs: object) -> None:
        nonlocal computed
        computed = True

    monkeypatch.setattr(command, "validate_stage_a_provenance", fail_gate)
    monkeypatch.setattr(command, "run_stage_a", forbidden_run)
    monkeypatch.setattr(
        sys,
        "argv",
        ["paired_feasible_stage_a.py", "--repo-root", str(tmp_path)],
    )
    with pytest.raises(StageAGateError, match="forced gate failure"):
        command.main()
    assert not computed
    assert not output.exists()

def test_r2_run_gate_requires_source_workspace_manifest_byte_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yaf_ai.exploration import paired_feasible_gates as gates

    entries: list[dict[str, object]] = []
    blobs: dict[str, bytes] = {}
    for run_id in gates.R2_RUN_IDS:
        log_bytes = (run_id + "-log\n").encode()
        summary_bytes = (run_id + "-summary\n").encode()
        entries.append(
            {
                "run_id": run_id,
                "sha256": {
                    "log.jsonl": hashlib.sha256(log_bytes).hexdigest(),
                    "summary.json": hashlib.sha256(summary_bytes).hexdigest(),
                },
            }
        )
        for filename, payload in (
            ("log.jsonl", log_bytes),
            ("summary.json", summary_bytes),
        ):
            relative = Path("artifacts/runs") / run_id / filename
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            blobs[relative.as_posix()] = payload
    manifest = json.dumps(entries, sort_keys=True).encode()
    manifest_path = tmp_path / gates.MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest)

    def committed_blob(_root: Path, _commit: str, path: Path) -> bytes:
        if path == gates.MANIFEST_PATH:
            return manifest
        return blobs[path.as_posix()]

    monkeypatch.setattr(gates, "_git_blob", committed_blob)
    gates._validate_r2_run_files(tmp_path)

    tampered = tmp_path / "artifacts/runs" / gates.R2_RUN_IDS[0] / "log.jsonl"
    tampered.write_bytes(b"tampered\n")
    with pytest.raises(gates.StageAGateError, match="differs from source commit"):
        gates._validate_r2_run_files(tmp_path)

def test_tolerance_sliver_witnesses_are_not_v2_valid() -> None:
    from yaf_ai.exploration.paired_meander import audit_trajectory

    terminal = PairedProposal(
        hardware=HardwareSpec(
            turn_count=5,
            feed_gap_ratio_ppm=27_302,
            terminal_ratio_ppm=77_650,
        ),
        state_a=StateControl(
            state="A", total_wire_length_um=100_000, span_ratio_ppm=800_000
        ),
        state_b=StateControl(
            state="B", total_wire_length_um=45_000, span_ratio_ppm=800_000
        ),
        proposer="tolerance-witness",
    )
    height = PairedProposal(
        hardware=HardwareSpec(
            turn_count=3,
            feed_gap_ratio_ppm=27_933,
            terminal_ratio_ppm=449_231,
        ),
        state_a=StateControl(
            state="A", total_wire_length_um=50_000, span_ratio_ppm=951_144
        ),
        state_b=StateControl(
            state="B", total_wire_length_um=34_961, span_ratio_ppm=951_144
        ),
        proposer="tolerance-witness",
    )
    assert audit_trajectory(terminal).valid
    assert audit_trajectory(height).valid
    assert _exact_nominal_rejection(terminal) == (
        "exact_nominal_constraint_failed:terminal:trajectory_index=00"
    )
    assert _exact_nominal_rejection(height) == (
        "exact_nominal_constraint_failed:height_min:trajectory_index=20"
    )
    for witness in (terminal, height):
        for representation in (LEGACY_REPRESENTATION, CONDITIONAL_REPRESENTATION):
            status, reason, _line = _status(0, representation, witness)
            assert status == "trajectory_infeasible"
            assert reason is not None and reason.startswith("exact_nominal_constraint_failed:")
