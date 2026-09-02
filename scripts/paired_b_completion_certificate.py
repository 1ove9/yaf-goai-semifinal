"""Run the solver-free B-parent A-only support certificate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_b_completion_coordinates import (
    CERTIFICATE_EXPECTED_SPANS,
    FROZEN_B_PARENTS,
    MAPPING_VERSION,
    P01,
    P02,
    BCompletionCoordinateInvariantError,
    CertificateSpanResult,
    FrozenBParent,
    SupportCertificateStatistics,
    combine_certificate_statistics,
    evaluate_certificate_span,
    summarize_parent_certificate,
)
from yaf_ai.exploration.paired_b_completion_gates import (
    PREREGISTRATION_COMMIT,
    SOURCE_EVIDENCE_COMMIT,
    BCompletionGateInputs,
    validate_b_completion_source_gates,
)
from yaf_ai.exploration.paired_feasible_coordinates import SPAN_BOUNDS
from yaf_ai.exploration.paired_feasible_gates import StageAGateError

STUDY_ID = "semifinal-paired-b-parent-conditional-completion-v1"
SPEC_REVISION = "1.0-b-parent-a-only-exact-support"
OUTPUT_DIRECTORY = Path(
    "artifacts/analysis/semifinal-paired-b-completion-v1-certificate"
)

CertificateStudyStatus = Literal[
    "support_certificate_passed", "support_certificate_failed"
]


class CertificateExecutionError(RuntimeError):
    """Raised when a certificate provenance or persistence invariant fails."""


class BCompletionCertificateSummary(BaseModel):
    """Machine-readable terminal certificate with byte-addressed provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: Literal["semifinal-paired-b-parent-conditional-completion-v1"] = (
        "semifinal-paired-b-parent-conditional-completion-v1"
    )
    spec_revision: Literal["1.0-b-parent-a-only-exact-support"] = (
        "1.0-b-parent-a-only-exact-support"
    )
    mapping_version: str = MAPPING_VERSION
    source_evidence_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    preregistration_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    conditional_implementation_blobs: dict[str, str]
    solver_calls: Literal[0] = 0
    openems_calls: Literal[0] = 0
    expected_span_count: int = CERTIFICATE_EXPECTED_SPANS
    checked_span_count: int = Field(ge=0, le=CERTIFICATE_EXPECTED_SPANS)
    failed_span_count: int = Field(ge=0)
    status: CertificateStudyStatus
    certificate: SupportCertificateStatistics
    provenance: BCompletionGateInputs

    @model_validator(mode="after")
    def validate_terminal_certificate(self) -> Self:
        """Require one complete, internally reconstructed terminal certificate."""

        if self.mapping_version != MAPPING_VERSION:
            raise ValueError("certificate mapping version changed")
        if self.source_evidence_commit != SOURCE_EVIDENCE_COMMIT:
            raise ValueError("certificate source evidence commit changed")
        if self.preregistration_commit != PREREGISTRATION_COMMIT:
            raise ValueError("certificate preregistration commit changed")
        if self.implementation_commit != self.provenance.implementation_commit:
            raise ValueError("certificate implementation commit changed")
        if self.provenance.execution_commit != self.implementation_commit:
            raise ValueError("certificate must execute at implementation HEAD")
        if (
            self.conditional_implementation_blobs
            != self.provenance.runtime_path_blobs
        ):
            raise ValueError("certificate runtime blob map changed")
        if self.expected_span_count != CERTIFICATE_EXPECTED_SPANS:
            raise ValueError("certificate expected span count changed")
        if (
            self.checked_span_count != self.certificate.checked_span_count
            or self.failed_span_count != self.certificate.failed_span_count
        ):
            raise ValueError("certificate top-level counts do not reconstruct")
        if self.certificate.status == "incomplete":
            raise ValueError("an incomplete certificate may not be persisted")
        expected_status: CertificateStudyStatus = (
            "support_certificate_passed"
            if self.certificate.status == "passed"
            else "support_certificate_failed"
        )
        if self.status != expected_status:
            raise ValueError("certificate terminal status changed")
        return self


def _require_coordinate_parent_identity(provenance: BCompletionGateInputs) -> None:
    """Bind coordinate constants to the two source-replayed frozen parents."""

    if tuple(parent.parent_id for parent in provenance.parents) != ("p01", "p02"):
        raise CertificateExecutionError("source parent order changed")
    for source, coordinate in zip(
        provenance.parents, FROZEN_B_PARENTS, strict=True
    ):
        identity = (
            source.parent_id == coordinate.parent_id,
            source.hardware_hash == coordinate.expected_hardware_hash,
            source.state_b_geometry_hash
            == coordinate.expected_state_b_geometry_hash,
            source.state_b_total_wire_length_um
            == coordinate.state_b.total_wire_length_um,
            source.state_b_span_ratio_ppm == coordinate.state_b.span_ratio_ppm,
            source.turn_count == coordinate.hardware.turn_count,
            source.feed_gap_ratio_ppm == coordinate.hardware.feed_gap_ratio_ppm,
            source.terminal_ratio_ppm == coordinate.hardware.terminal_ratio_ppm,
        )
        if not all(identity):
            raise CertificateExecutionError(
                f"coordinate parent differs from source replay: {source.parent_id}"
            )


def _iter_parent_results(
    parent: FrozenBParent,
    spans: Iterable[int],
) -> Iterator[CertificateSpanResult]:
    """Stream every requested span without retaining the exhaustive support."""

    for span in spans:
        yield evaluate_certificate_span(parent, span)


def run_support_certificate() -> SupportCertificateStatistics:
    """Traverse both complete parent supports in the preregistered order."""

    spans = range(SPAN_BOUNDS[0], SPAN_BOUNDS[1] + 1)
    p01 = summarize_parent_certificate(P01, _iter_parent_results(P01, spans))
    p02 = summarize_parent_certificate(P02, _iter_parent_results(P02, spans))
    return combine_certificate_statistics(p01, p02)


def build_summary(
    provenance: BCompletionGateInputs,
    certificate: SupportCertificateStatistics,
) -> BCompletionCertificateSummary:
    """Build the sole legal terminal certificate summary."""

    status: CertificateStudyStatus = (
        "support_certificate_passed"
        if certificate.status == "passed"
        else "support_certificate_failed"
    )
    return BCompletionCertificateSummary(
        source_evidence_commit=SOURCE_EVIDENCE_COMMIT,
        preregistration_commit=PREREGISTRATION_COMMIT,
        implementation_commit=provenance.implementation_commit,
        conditional_implementation_blobs=provenance.runtime_path_blobs,
        checked_span_count=certificate.checked_span_count,
        failed_span_count=certificate.failed_span_count,
        status=status,
        certificate=certificate,
        provenance=provenance,
    )


def render_report(summary: BCompletionCertificateSummary) -> str:
    """Render a deterministic human-readable certificate report."""

    lines = [
        "# B-parent A-only support certificate",
        "",
        f"- Study: `{summary.study_id}`",
        f"- Status: `{summary.status}`",
        f"- Mapping: `{summary.mapping_version}`",
        f"- Implementation commit: `{summary.implementation_commit}`",
        f"- Checked spans: `{summary.checked_span_count}/{summary.expected_span_count}`",
        f"- Failed spans: `{summary.failed_span_count}`",
        "- Solver calls: `0`",
        "- openEMS calls: `0`",
        "",
        "## Parent totals",
        "",
        "| Parent | Checked | Failed | Status |",
        "|---|---:|---:|---|",
    ]
    for parent in summary.certificate.parents:
        lines.append(
            f"| {parent.parent_id.upper()} | {parent.checked_span_count} "
            f"| {parent.failed_span_count} | `{parent.status}` |"
        )
    lines.extend(("", "## Failure tallies and first witnesses", ""))
    if summary.failed_span_count == 0:
        lines.append("No frozen support check failed.")
    else:
        for parent in summary.certificate.parents:
            lines.extend((f"### {parent.parent_id.upper()}", ""))
            if not parent.failure_tallies:
                lines.extend(("No failures.", ""))
                continue
            for tally in parent.failure_tallies:
                witness = tally.first_witness
                lines.append(
                    f"- `{tally.failure_class}`: count={tally.count}; first span="
                    f"{witness.span_ratio_ppm}; length={witness.length_um}; "
                    f"exact={witness.exact_legal}; audit={witness.audit_legal}; "
                    f"detail={witness.detail}"
                )
            lines.append("")
    lines.extend(("", "## Conditional implementation blobs", ""))
    for path, blob in sorted(summary.conditional_implementation_blobs.items()):
        lines.append(f"- `{path}`: `{blob}`")
    lines.extend(
        (
            "",
            "This exhaustive certificate is solver-free. It is a support-map "
            "qualification, not an antenna result or independent-solver confirmation.",
            "",
        )
    )
    return "\n".join(lines)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_outputs(
    output_directory: Path,
    summary: BCompletionCertificateSummary,
) -> None:
    """Atomically persist LF-only machine and human certificate evidence."""

    summary_bytes = (
        json.dumps(
            summary.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    report_bytes = render_report(summary).encode("utf-8")
    if b"\r" in summary_bytes or b"\r" in report_bytes:
        raise CertificateExecutionError("certificate outputs must be LF-only")
    _atomic_write(output_directory / "report.md", report_bytes)
    _atomic_write(output_directory / "summary.json", summary_bytes)


def execute_certificate(
    repo_root: Path,
    implementation_commit: str,
) -> BCompletionCertificateSummary:
    """Gate, traverse, and persist the complete solver-free certificate."""

    root = repo_root.resolve()
    provenance = validate_b_completion_source_gates(
        root,
        implementation_commit=implementation_commit,
        execution_commit=implementation_commit,
    )
    _require_coordinate_parent_identity(provenance)
    certificate = run_support_certificate()
    summary = build_summary(provenance, certificate)
    write_outputs(root / OUTPUT_DIRECTORY, summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--implementation-commit",
        required=True,
        help="Full commit-2 hash; it must equal HEAD while the certificate runs.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root; output remains fixed by the preregistration.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        summary = execute_certificate(
            args.repo_root,
            implementation_commit=args.implementation_commit,
        )
    except (
        BCompletionCoordinateInvariantError,
        CertificateExecutionError,
        StageAGateError,
        OSError,
        ValueError,
    ) as error:
        print(
            f"B-parent support certificate aborted: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    print(
        f"{summary.status}: checked={summary.checked_span_count}/"
        f"{summary.expected_span_count}; failed={summary.failed_span_count}; "
        f"summary={args.repo_root.resolve() / OUTPUT_DIRECTORY / 'summary.json'}"
    )
    return 0 if summary.status == "support_certificate_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
