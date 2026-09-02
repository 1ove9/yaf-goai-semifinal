"""Tests for committed-log-only semifinal candidate freezing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yaf_ai.exploration.paired_candidate_report import (
    render_candidate_report,
    write_or_verify_candidate_report,
)
from yaf_ai.exploration.paired_candidates import (
    BATCH_EXECUTION_COMMIT,
    ES_RUN_IDS,
    MANUAL_BASELINE_COMMIT,
    MANUAL_RUN_IDS,
    RANDOM_RUN_IDS,
    SOURCE_EVIDENCE_COMMIT,
    SOURCE_MANIFEST_ENTRY_COUNT,
    SOURCE_MANIFEST_SHA256,
    CandidateFreezeError,
    _committed_bytes,
    _load_category_records,
    _manifest_index,
    _require_ancestor,
    _validate_manifest_extension,
    build_candidate_freeze,
    write_once_or_match,
    write_or_verify_candidate_freeze,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pinned_manifest_bytes() -> bytes:
    return _committed_bytes(_repo_root(), Path("artifacts/runs/manifest.json"))


def test_candidate_freeze_recomputes_three_exact_source_pools() -> None:
    document = build_candidate_freeze(_repo_root())
    assert document.source_evidence_commit == SOURCE_EVIDENCE_COMMIT
    assert document.source_manifest_sha256 == SOURCE_MANIFEST_SHA256
    assert document.matrix_budget_complete
    assert not document.openems_cross_check_authorized
    assert document.verdict_ceiling == "insufficient_evidence"
    es, random, manual = document.candidates
    assert es.category == "top-es"
    assert es.source_run_ids == ES_RUN_IDS
    assert es.source_record_count == 1_800
    assert es.valid_record_count == 48
    assert es.valid_pair_search
    assert es.positive_eligible
    assert es.source_run_id == "semifinal-paired-es-warm-s101"
    assert random.category == "top-random"
    assert random.source_run_ids == RANDOM_RUN_IDS
    assert random.source_record_count == 900
    assert random.valid_record_count == 0
    assert not random.valid_pair_search
    assert not random.positive_eligible
    assert manual.category == "manual-baseline"
    assert manual.source_run_ids == MANUAL_RUN_IDS
    assert manual.source_record_count == 756
    assert manual.valid_record_count == 0
    assert not manual.valid_pair_search
    assert not manual.positive_eligible
    assert manual.source_run_id == "semifinal-paired-manual-baseline"
    assert manual.source_step_index == 288
    assert es.source_step_index == 213
    assert es.pair_hash == ("8a4ad18c710ec185728fd5bff0e6f16461aea29362024893e1bb6ddd3dcc73ca")
    assert random.source_run_id == "semifinal-paired-random-s202"
    assert random.source_step_index == 130
    assert random.pair_hash == ("cbf69fb9b291f64fbf5b965ee2ad6910542cecf54068aa485aabfbafcc03c130")
    assert manual.pair_hash == ("e9f13ba6ede326e3adc4a48ba0a7658c0ca712434550ed98bffab681d262b321")
    assert [item.valid_pair_count for item in document.agent_run_statistics] == [
        0,
        0,
        0,
        0,
        0,
        0,
        48,
        0,
        0,
    ]
    effect = document.effect_assessment
    assert effect.relative_reduction_fraction == pytest.approx(0.04674341445557906)
    assert not effect.passed
    diagnostic = document.validity_gate_diagnostic
    assert diagnostic.source_run_id == "semifinal-paired-es-warm-s303"
    assert diagnostic.source_step_index == 214
    assert diagnostic.state_a_selected_index == 100
    assert diagnostic.state_b_selected_index == 0
    assert not diagnostic.valid_pair_search
    assert diagnostic.apparent_reduction_fraction == pytest.approx(0.20582745527777901)


def test_candidate_freeze_write_and_verify_are_byte_deterministic(
    tmp_path: Path,
) -> None:
    output = tmp_path / "frozen_candidates.json"
    report = tmp_path / "report.md"
    written = write_or_verify_candidate_freeze(
        _repo_root(),
        verify=False,
        output_path=output,
    )
    write_or_verify_candidate_report(
        _repo_root(),
        written,
        verify=False,
        report_path=report,
    )
    written_again = write_or_verify_candidate_freeze(
        _repo_root(),
        verify=False,
        output_path=output,
    )
    verified = write_or_verify_candidate_freeze(
        _repo_root(),
        verify=True,
        output_path=output,
    )
    write_or_verify_candidate_report(
        _repo_root(),
        verified,
        verify=True,
        report_path=report,
    )
    assert written == written_again == verified
    assert b"\r" not in output.read_bytes()
    assert b"\r" not in report.read_bytes()
    assert report.read_bytes() == render_candidate_report(written)
    output.write_bytes(output.read_bytes() + b" ")
    with pytest.raises(CandidateFreezeError, match="refusing to overwrite"):
        write_or_verify_candidate_freeze(
            _repo_root(),
            verify=False,
            output_path=output,
        )
    with pytest.raises(CandidateFreezeError, match="does not recompute"):
        write_or_verify_candidate_freeze(
            _repo_root(),
            verify=True,
            output_path=output,
        )


def test_candidate_metrics_and_proposals_are_source_complete() -> None:
    document = build_candidate_freeze(_repo_root())
    for candidate in document.candidates:
        assert candidate.source_log_sha256
        assert candidate.source_summary_sha256
        assert candidate.pair_hash
        assert candidate.hardware_hash
        assert candidate.state_a_geometry_hash
        assert candidate.state_b_geometry_hash
        assert candidate.base_score == candidate.metrics.base_score
        assert candidate.search_score == candidate.metrics.search_score
        assert candidate.valid_pair_search == candidate.metrics.valid_pair_search
        assert candidate.trajectory.valid
        assert candidate.proposal.hardware.schema_version == 1


def test_freeze_source_contains_no_draft_run_or_openems_dependency() -> None:
    source = (_repo_root() / "yaf_ai/exploration/paired_candidates.py").read_text(encoding="utf-8")
    assert 'Path("runs")' not in source
    assert "openems_adapter" not in source
    assert "run_paired_adaptive" not in source
    assert "from yaf_ai.exploration.paired_runner import load_paired_evaluations" not in source


def test_manifest_extension_allows_pure_append() -> None:
    manifest_path = _repo_root() / "artifacts/runs/manifest.json"
    pinned_payload = _pinned_manifest_bytes()
    current_payload = manifest_path.read_bytes()
    pinned_index = _manifest_index(pinned_payload)
    current_index = _validate_manifest_extension(pinned_payload, current_payload)

    assert len(pinned_index) == SOURCE_MANIFEST_ENTRY_COUNT
    assert len(current_index) >= SOURCE_MANIFEST_ENTRY_COUNT + 1
    assert set(pinned_index) < set(current_index)


def test_manifest_extension_rejects_tampered_missing_and_duplicate_entries() -> None:
    pinned_payload = _pinned_manifest_bytes()
    manifest_path = _repo_root() / "artifacts/runs/manifest.json"
    current = json.loads(manifest_path.read_bytes())

    tampered = json.loads(manifest_path.read_bytes())
    tampered[0]["note"] = f"{tampered[0]['note']} tampered"
    with pytest.raises(CandidateFreezeError, match="modified or reordered"):
        _validate_manifest_extension(
            pinned_payload,
            json.dumps(tampered).encode("utf-8"),
        )

    missing = current[1:]
    with pytest.raises(CandidateFreezeError, match="missing pinned runs"):
        _validate_manifest_extension(
            pinned_payload,
            json.dumps(missing).encode("utf-8"),
        )

    duplicate = [*current, current[0]]
    with pytest.raises(CandidateFreezeError, match="duplicate"):
        _validate_manifest_extension(
            pinned_payload,
            json.dumps(duplicate).encode("utf-8"),
        )


def test_manifest_index_rejects_invalid_digest() -> None:
    manifest_path = _repo_root() / "artifacts/runs/manifest.json"
    invalid = json.loads(manifest_path.read_bytes())
    invalid[0]["sha256"]["log.jsonl"] = "0" * 63
    with pytest.raises(CandidateFreezeError, match="invalid SHA-256"):
        _manifest_index(json.dumps(invalid).encode("utf-8"))


def test_source_run_digest_must_match_manifest_entry() -> None:
    manifest_path = _repo_root() / "artifacts/runs/manifest.json"
    payload = json.loads(manifest_path.read_bytes())
    run_id = "semifinal-paired-random-s101"
    entry = next(item for item in payload if item["run_id"] == run_id)
    entry["sha256"]["log.jsonl"] = "0" * 64
    manifest = _manifest_index(json.dumps(payload).encode("utf-8"))
    with pytest.raises(CandidateFreezeError, match="digest binding failed"):
        _load_category_records(
            _repo_root(),
            (run_id,),
            require_full_agent_run=True,
            manifest=manifest,
        )


def test_default_candidate_artifacts_recompute_from_committed_sources() -> None:
    document = write_or_verify_candidate_freeze(_repo_root(), verify=True)
    write_or_verify_candidate_report(
        _repo_root(),
        document,
        verify=True,
    )
    report = render_candidate_report(document).decode("utf-8")
    assert "NEC2-only / insufficient_evidence" in report
    assert "4.674%" in report
    assert "20.583%" in report
    assert "not `YAF-M1`" in report
    assert "openEMS cross-check: not authorized" in report


def test_report_values_and_validity_wording_come_from_document() -> None:
    document = build_candidate_freeze(_repo_root())
    top_es, top_random, manual = document.candidates
    changed_state_a = top_es.metrics.state_a.model_copy(
        update={
            "selected_frequency_hz": 2_412_300_000.0,
            "selected_s11_db": -7.321,
        }
    )
    changed_metrics = top_es.metrics.model_copy(update={"state_a": changed_state_a})
    changed_top_es = top_es.model_copy(update={"pair_hash": "a" * 64, "metrics": changed_metrics})
    changed_diagnostic = document.validity_gate_diagnostic.model_copy(
        update={"valid_pair_search": True}
    )
    changed_document = document.model_copy(
        update={
            "candidates": (changed_top_es, top_random, manual),
            "validity_gate_diagnostic": changed_diagnostic,
        }
    )

    report = render_candidate_report(changed_document).decode("utf-8")

    assert "paired-state hypothesis aaaaaaaaaaaa..." in report
    assert "2.4123 GHz" in report
    assert "S11=-7.321 dB" in report
    assert "raw-score leader also passed the validity gate" in report
    assert "rejected the invalid raw-score leader" not in report


def test_atomic_writer_leaves_no_partial_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "atomic.json"

    def fail_link(_source: object, _destination: object) -> None:
        raise OSError("injected publish failure")

    monkeypatch.setattr(
        "yaf_ai.exploration.paired_candidates.os.link",
        fail_link,
    )
    with pytest.raises(CandidateFreezeError, match="cannot create freeze artifact"):
        write_once_or_match(destination, b"complete bytes\n")

    assert not destination.exists()
    assert tuple(tmp_path.glob(".atomic.json.*.tmp")) == ()


def test_evidence_commit_descends_from_execution_and_manual_baseline() -> None:
    for predecessor in (BATCH_EXECUTION_COMMIT, MANUAL_BASELINE_COMMIT):
        _require_ancestor(
            _repo_root(),
            predecessor,
            SOURCE_EVIDENCE_COMMIT,
        )


def test_report_handles_a_matrix_with_no_eligible_es_candidate() -> None:
    document = build_candidate_freeze(_repo_root())
    top_es, top_random, manual = document.candidates
    diagnostic_top = top_es.model_copy(
        update={
            "positive_eligible": False,
            "valid_pair_search": False,
        }
    )
    zero_statistics = tuple(
        statistic.model_copy(
            update={
                "valid_pair_count": 0,
                "valid_pair_fraction": 0.0,
                "best_valid_base_score": None,
            }
        )
        for statistic in document.agent_run_statistics
    )
    changed_document = document.model_copy(
        update={
            "candidates": (diagnostic_top, top_random, manual),
            "agent_run_statistics": zero_statistics,
        }
    )

    report = render_candidate_report(changed_document).decode("utf-8")

    assert "No NEC2-valid two-state computational hypothesis survived" in report
    assert "No matrix cell supplied a NEC2-valid paired proposal" in report
    assert "A NEC2-valid two-state computational hypothesis emerged" not in report
    assert "diagnostic-only / insufficient_evidence" in report
