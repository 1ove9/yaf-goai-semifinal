"""Tests for the solver-free B-parent support-certificate CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts import paired_b_completion_certificate as certificate_cli
from yaf_ai.exploration.paired_b_completion_coordinates import (
    CERTIFICATE_EXPECTED_SPANS_PER_PARENT,
    P01,
    CertificateFailureTally,
    CertificateFailureWitness,
    CertificateSpanResult,
    ParentCertificateStatistics,
    ParentID,
    SupportCertificateStatistics,
    combine_certificate_statistics,
)
from yaf_ai.exploration.paired_b_completion_gates import (
    FROZEN_PARENTS,
    PREREGISTRATION_COMMIT,
    RUNTIME_PATHS,
    SOURCE_EVIDENCE_COMMIT,
    SOURCE_MANIFEST_ENTRY_COUNT,
    SOURCE_MANIFEST_SHA256,
    BCompletionGateInputs,
)
from yaf_ai.exploration.paired_feasible_coordinates import SPAN_BOUNDS
from yaf_ai.exploration.paired_feasible_gates import (
    BUDGET_CONFIG_HASH,
    BUDGET_SOURCE_COMMIT,
    BUDGET_SUMMARY_SHA256,
)


def _provenance() -> BCompletionGateInputs:
    runtime_blobs = {
        path.as_posix(): f"{index + 1:040x}"
        for index, path in enumerate(RUNTIME_PATHS)
    }
    return BCompletionGateInputs(
        source_evidence_commit=SOURCE_EVIDENCE_COMMIT,
        preregistration_commit=PREREGISTRATION_COMMIT,
        implementation_commit="b" * 40,
        execution_commit="b" * 40,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_manifest_entry_count=SOURCE_MANIFEST_ENTRY_COUNT,
        accepted_record_count=6000,
        stage_b_run_count=10,
        parents=FROZEN_PARENTS,
        budget_source_commit=BUDGET_SOURCE_COMMIT,
        budget_summary_sha256=BUDGET_SUMMARY_SHA256,
        budget_config_hash=BUDGET_CONFIG_HASH,
        frozen_science_blobs={"frozen.py": "a" * 40},
        runtime_path_blobs=runtime_blobs,
        clean_tracked_code=True,
    )


def _parent_statistics(
    parent_id: ParentID,
    *,
    failed: bool,
) -> ParentCertificateStatistics:
    if not failed:
        return ParentCertificateStatistics(
            parent_id=parent_id,
            checked_span_count=CERTIFICATE_EXPECTED_SPANS_PER_PARENT,
            failed_span_count=0,
            failure_tallies=(),
            status="passed",
        )
    witness = CertificateFailureWitness(
        failure_class="lower_round_trip_failed",
        span_ratio_ppm=SPAN_BOUNDS[0],
        length_um=50_000,
        detail="synthetic first witness",
    )
    return ParentCertificateStatistics(
        parent_id=parent_id,
        checked_span_count=CERTIFICATE_EXPECTED_SPANS_PER_PARENT,
        failed_span_count=1,
        failure_tallies=(
            CertificateFailureTally(
                failure_class=witness.failure_class,
                count=1,
                first_witness=witness,
            ),
        ),
        status="failed",
    )


def _certificate(*, failed: bool = False) -> SupportCertificateStatistics:
    return combine_certificate_statistics(
        _parent_statistics("p01", failed=failed),
        _parent_statistics("p02", failed=False),
    )


def test_small_span_iterator_visits_every_span_after_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visited: list[int] = []

    def fake_evaluate(
        parent: object,
        span: int,
    ) -> CertificateSpanResult:
        del parent
        visited.append(span)
        failures: tuple[CertificateFailureWitness, ...] = ()
        if span == SPAN_BOUNDS[0]:
            failures = (
                CertificateFailureWitness(
                    failure_class="lower_round_trip_failed",
                    span_ratio_ppm=span,
                    length_um=50_000,
                    detail="small-span failure",
                ),
            )
        return CertificateSpanResult(
            parent_id="p01",
            span_ratio_ppm=span,
            lower_legal_length_um=50_000,
            failures=failures,
        )

    monkeypatch.setattr(certificate_cli, "evaluate_certificate_span", fake_evaluate)
    spans = range(SPAN_BOUNDS[0], SPAN_BOUNDS[0] + 3)
    results = tuple(certificate_cli._iter_parent_results(P01, spans))
    assert visited == list(spans)
    assert results[0].failures
    assert results[1].passed and results[2].passed


def test_summary_freezes_runtime_map_counts_witnesses_and_zero_solver_calls() -> None:
    provenance = _provenance()
    summary = certificate_cli.build_summary(provenance, _certificate(failed=True))
    assert summary.status == "support_certificate_failed"
    assert summary.checked_span_count == 480_002
    assert summary.failed_span_count == 1
    assert summary.solver_calls == 0
    assert summary.openems_calls == 0
    assert summary.conditional_implementation_blobs == provenance.runtime_path_blobs
    tally = summary.certificate.parents[0].failure_tallies[0]
    assert tally.count == 1
    assert tally.first_witness.span_ratio_ppm == SPAN_BOUNDS[0]


def test_incomplete_certificate_cannot_be_persisted() -> None:
    partial = SupportCertificateStatistics(
        checked_span_count=0,
        failed_span_count=0,
        parents=(
            ParentCertificateStatistics(
                parent_id="p01",
                checked_span_count=0,
                failed_span_count=0,
                failure_tallies=(),
                status="incomplete",
            ),
            ParentCertificateStatistics(
                parent_id="p02",
                checked_span_count=0,
                failed_span_count=0,
                failure_tallies=(),
                status="incomplete",
            ),
        ),
        status="incomplete",
    )
    with pytest.raises(ValidationError, match="incomplete"):
        certificate_cli.build_summary(_provenance(), partial)


def test_outputs_are_atomic_lf_only_and_include_runtime_provenance(
    tmp_path: Path,
) -> None:
    summary = certificate_cli.build_summary(_provenance(), _certificate())
    certificate_cli.write_outputs(tmp_path, summary)
    summary_bytes = (tmp_path / "summary.json").read_bytes()
    report_bytes = (tmp_path / "report.md").read_bytes()
    assert b"\r" not in summary_bytes
    assert b"\r" not in report_bytes
    assert summary_bytes.endswith(b"\n")
    assert report_bytes.endswith(b"\n")
    assert not (tmp_path / "summary.json.tmp").exists()
    assert not (tmp_path / "report.md.tmp").exists()
    payload = json.loads(summary_bytes)
    assert payload["status"] == "support_certificate_passed"
    assert payload["conditional_implementation_blobs"] == (
        summary.conditional_implementation_blobs
    )
    assert "Solver calls: `0`" in report_bytes.decode("utf-8")


def test_execute_calls_source_gate_before_traversal_and_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provenance = _provenance()
    events: list[str] = []

    def fake_gate(
        root: Path,
        implementation_commit: str,
        execution_commit: str,
    ) -> BCompletionGateInputs:
        assert root == tmp_path.resolve()
        assert implementation_commit == execution_commit == "b" * 40
        events.append("gate")
        return provenance

    def fake_run() -> SupportCertificateStatistics:
        events.append("traverse")
        return _certificate()

    def fake_write(
        output: Path,
        summary: certificate_cli.BCompletionCertificateSummary,
    ) -> None:
        assert output == tmp_path.resolve() / certificate_cli.OUTPUT_DIRECTORY
        assert summary.status == "support_certificate_passed"
        events.append("write")

    monkeypatch.setattr(
        certificate_cli, "validate_b_completion_source_gates", fake_gate
    )
    monkeypatch.setattr(certificate_cli, "run_support_certificate", fake_run)
    monkeypatch.setattr(certificate_cli, "write_outputs", fake_write)
    result = certificate_cli.execute_certificate(tmp_path, "b" * 40)
    assert result.status == "support_certificate_passed"
    assert events == ["gate", "traverse", "write"]


def test_coordinate_parent_gate_rejects_source_identity_drift() -> None:
    payload = _provenance().model_dump(mode="json")
    payload["parents"][0]["state_b_total_wire_length_um"] += 1
    drifted = BCompletionGateInputs.model_validate(payload)
    with pytest.raises(
        certificate_cli.CertificateExecutionError,
        match="coordinate parent differs",
    ):
        certificate_cli._require_coordinate_parent_identity(drifted)
