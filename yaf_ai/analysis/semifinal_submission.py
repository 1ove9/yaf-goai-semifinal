"""Build the solver-free GOAI semifinal evidence package from archived bytes."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from yaf_ai.exploration.paired_candidates import (
    CandidateFreezeDocument,
    FrozenCategoryCandidate,
    build_candidate_freeze,
)
from yaf_ai.exploration.paired_meander import PairedProposal, _build_quantized_geometry
from yaf_ai.exploration.paired_runner import PairedEvaluationRecord
from yaf_core.domain.geometry import Geometry

SUBMISSION_DIRECTORY = Path("artifacts/analysis/semifinal-submission")
SUBMISSION_MANIFEST_PATH = Path("artifacts/runs/manifest.json")
SUMMARY_PATH = SUBMISSION_DIRECTORY / "summary.json"
ARTIFACT_PATH = SUBMISSION_DIRECTORY / "artifact.json"
REPORT_PATH = SUBMISSION_DIRECTORY / "report.md"
CANDIDATE_CARD_PATH = SUBMISSION_DIRECTORY / "candidate-card.md"
EVIDENCE_INDEX_PATH = SUBMISSION_DIRECTORY / "evidence-index.md"
GEOMETRY_PNG_PATH = SUBMISSION_DIRECTORY / "candidate-geometry.png"
TRAJECTORY_GIF_PATH = SUBMISSION_DIRECTORY / "candidate-trajectory.gif"

FROZEN_CANDIDATES_PATH = Path(
    "artifacts/analysis/semifinal-paired-agent-batch/frozen_candidates.json"
)
FROZEN_REPORT_PATH = Path("artifacts/analysis/semifinal-paired-agent-batch/report.md")
STATIC_DAY6_REPORT_PATH = Path("artifacts/analysis/day6-freeform/report.md")
STATIC_DAY6_SUMMARY_PATH = Path("artifacts/analysis/day6-freeform/summary.json")
MANUAL_BASELINE_RUN_ID = "semifinal-paired-manual-baseline"
ROD_R2_RUN_ID = "semifinal-wifi58-rod-renderer-anchor-r2-combined"
MEANDER_R3_RUN_ID = "semifinal-wifi58-meander-renderer-anchor-r3-combined"
STATIC_DAY6_EVIDENCE_COMMIT = "acbf4736b8755b682d215e16fe479ffff534360d"
MANUAL_BASELINE_EVIDENCE_COMMIT = "906835eceeae2e48a652e2b7fa891fd3e8461440"
MEANDER_R3_EVIDENCE_COMMIT = "6bee5eeac5642386f7015bf496e8a592424cb75c"
ROD_R2_EVIDENCE_COMMIT = "ba53596f8191ec1a820ae7470349c89091a5bbe8"
SUBMISSION_MANIFEST_ENTRY_COUNT = 219
SUBMISSION_MANIFEST_SHA256 = "cd6d8bd106ae6b7da478c836913a84511f1a484e55641e07f21cbe17013dfb8c"
CANDIDATE_FREEZE_COMMIT = "4a8222eb7528a24acaa5879e7afa2398f0413740"
STATIC_DAY6_REPORT_SHA256 = "07426556777d842bd71489a4e866f6a5487714a95e0f10b3ec52f137aac95d00"
STATIC_DAY6_SUMMARY_SHA256 = "28def8a7b5a204e7da394f458ab6bd6e027f124f0da025571065c904ef1a4df1"
FROZEN_CANDIDATES_SHA256 = "0e814e2cc85ae0fe361c91a4d7338ae2175369b494eb49cdef8bd165338695d5"
SOURCE_MANIFEST_SHA256 = "6de538d4ec44931eda14cd4ce1828b2962176c8af500106f48bb0fbba331ffcb"
MANUAL_BASELINE_LOG_SHA256 = "838fd4d77e6fe15ad7bd7625d95d6a8071a96cd6c1e2483dcae77824a80420e4"
MANUAL_BASELINE_SUMMARY_SHA256 = "a089fa75ac3891ea7895b86962574aefda778c9a2d8728d1f29c2db7027cb133"
RANDOM_SOURCE_RUN_ID = "semifinal-paired-random-s202"
RANDOM_SOURCE_LOG_SHA256 = "6d314da8045b620f8303b1335921d1d770d3cac6a5bff1e91fceacb6a6a0626e"
RANDOM_SOURCE_SUMMARY_SHA256 = "2e9aff581abb264d5a0a7babe0cc48ba0bf61e19c6888051c3d7bfb175ac8bd9"
MEANDER_R3_LOG_SHA256 = "0e9da50876fa679870160ba9349a8391c18d7917355d7cef50177899bb967a9f"
MEANDER_R3_SUMMARY_SHA256 = "d5ac661dc0251d0e7dcecf7a88d967a2c510e568e3338a45c5e84399254f67a9"
ROD_R2_LOG_SHA256 = "b3dd5214aae9c0f48f1051514109207bbb86c9f5cc3b832afc6180da62347079"
ROD_R2_SUMMARY_SHA256 = "6981fb426ea700a31aa4b716c845bb7b6b6a99a30a41e1013b090eed89dcf6f1"
REPORT_TITLE = (
    "From a static dual-band negative result within a frozen search space, budget, "
    "and seed set to a shared-hardware two-state computational hypothesis"
)
SUBMISSION_EVIDENCE_FILES = ("log.jsonl", "summary.json")


class SemifinalSubmissionError(RuntimeError):
    """Raised when the submission package cannot be proved from archived bytes."""


class ProbeEvidence(BaseModel):
    """Small subset of one archived openEMS probe record."""

    model_config = ConfigDict(frozen=True, extra="allow")

    exists: bool
    parseable_sample_count: int = Field(ge=0)


class SubmissionManifestEntry(BaseModel):
    """Read-only manifest fields required by the submission verifier."""

    model_config = ConfigDict(frozen=True, extra="allow")

    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    sha256: dict[str, str]

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        """Require exactly the two lowercase evidence-file digests."""

        if set(self.sha256) != set(SUBMISSION_EVIDENCE_FILES):
            raise ValueError(
                f"sha256 must contain exactly {SUBMISSION_EVIDENCE_FILES}"
            )
        if any(
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.sha256.values()
        ):
            raise ValueError("sha256 values must be lowercase SHA-256 digests")
        return self


class HarnessDiagnostic(BaseModel):
    """Small subset of one archived rod harness diagnostic."""

    model_config = ConfigDict(frozen=True, extra="allow")

    label: str
    launched: bool
    normal_exit: bool
    exit_code: int | None
    current_probe: ProbeEvidence
    voltage_probe: ProbeEvidence


class RodRepairDiagnostic(BaseModel):
    """Frozen pass/fail evidence for the rod-renderer repair gate."""

    model_config = ConfigDict(frozen=True, extra="allow")

    gate_passed: bool
    failure_reasons: tuple[str, ...]
    legacy_a: HarnessDiagnostic
    repaired_b: HarnessDiagnostic
    s11_evaluated: bool


class RodR2Summary(BaseModel):
    """Fields used from the terminal rod-renderer r2 summary."""

    model_config = ConfigDict(frozen=True, extra="allow")

    run_id: Literal["semifinal-wifi58-rod-renderer-anchor-r2-combined"]
    result_status: Literal["repair_not_confirmed"]
    failure_type: Literal["repair_not_confirmed"]
    anchor_released: Literal[False]
    scientific_verdict: None
    verdict: None
    steps_completed: int
    solver_mode_counts: dict[str, int]
    repair_diagnostic: RodRepairDiagnostic


class CrossSolverDecision(BaseModel):
    """Descriptive r3 agreement metrics that did not release the anchor."""

    model_config = ConfigDict(frozen=True, extra="allow")

    curve_pearson_correlation: float
    resonance_relative_difference: float


class AnchorR3Decision(BaseModel):
    """Terminal thin-box meander anchor decision used as historical context."""

    model_config = ConfigDict(frozen=True, extra="allow")

    anchor_released: Literal[False]
    verdict: Literal["not_released_out_of_band_high"]
    openems_16x_to_32x_resonance_shift: float
    cross_solver_decision: CrossSolverDecision


class MeanderR3Summary(BaseModel):
    """Small, frozen subset of the terminal thin-box anchor summary."""

    model_config = ConfigDict(frozen=True, extra="allow")

    run_id: Literal["semifinal-wifi58-meander-renderer-anchor-r3-combined"]
    decision: AnchorR3Decision


class ManualBaselineRunSummary(BaseModel):
    """Archived manual comparator counts used by the frozen effect assessment."""

    model_config = ConfigDict(frozen=True, extra="allow")

    run_id: Literal["semifinal-paired-manual-baseline"]
    pair_total: int
    scored_pairs: int
    valid_pair_count: int


class StaticDay6ArchivedSummary(BaseModel):
    """Claim-ceiling field read from the committed Day 6 static study."""

    model_config = ConfigDict(frozen=True, extra="allow")

    final_verdict: Literal["insufficient_evidence"]


class CandidateStateSummary(BaseModel):
    """One state on the frozen NEC2-only computational hypothesis card."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["A", "B"]
    total_wire_length_mm: float
    span_ratio: float
    selected_frequency_ghz: float
    selected_s11_db: float
    reflected_power_fraction: float
    selected_index: int
    valid_internal_minimum: bool
    geometry_hash: str


class CandidateCardSummary(BaseModel):
    """Source-addressed card for the sole frozen paired-state hypothesis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: Literal["paired-state computational hypothesis"]
    source_run_id: str
    source_step_index: int
    source_proposal_index: int
    hardware_hash: str
    pair_hash: str
    mechanism_version: str
    box_size_mm: float
    wire_radius_mm: float
    turn_count: int
    feed_gap_ratio_ppm: int
    terminal_ratio_ppm: int
    physical_feed_gap_mm: float
    state_a: CandidateStateSummary
    state_b: CandidateStateSummary
    trajectory_point_count: int
    trajectory_valid: bool
    minimum_clearance_mm: float
    minimum_pitch_mm: float
    minimum_height_mm: float
    maximum_adjacent_node_displacement_mm: float
    source_log_sha256: str
    source_summary_sha256: str


class MatrixCellSummary(BaseModel):
    """One frozen agent-by-seed cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: Literal["random", "es-cold", "es-warm"]
    seed: int
    accepted_pairs: int
    valid_pairs: int
    rejected_proposals: int
    proposal_attempts: int
    subprocess_curves: int
    wall_seconds: float


class EffectGateSummary(BaseModel):
    """The preregistered reflected-power effect gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: Literal["worst-state-reflected-power-fraction"]
    candidate_value: float
    manual_reference_value: float
    maximum_allowed_value: float
    observed_reduction_fraction: float
    required_reduction_fraction: float
    passed: bool


class InstrumentSummary(BaseModel):
    """Submission-facing status of independent openEMS confirmation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    thin_box_r3_run_id: str
    thin_box_r3_verdict: str
    thin_box_r3_anchor_released: bool
    thin_box_r3_frequency_gap_fraction: float
    thin_box_r3_pearson: float
    thin_box_r3_last_shift_fraction: float
    rod_r2_run_id: str
    rod_r2_result_status: str
    rod_r2_repair_gate_passed: bool
    rod_r2_failure_reasons: tuple[str, ...]
    rod_r2_repaired_voltage_probe_exists: bool
    rod_r2_repaired_voltage_samples: int
    rod_r2_repaired_current_probe_exists: bool
    rod_r2_repaired_current_samples: int
    candidate_openems_authorized: bool
    candidate_openems_executed: bool


class ArchiveSummary(BaseModel):
    """Current full-archive integrity status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_entry_count: int
    verified_ok_count: int
    manifest_sha256: str
    all_ok: bool


class CommittedStaticContextSummary(BaseModel):
    """Historical static-study context bound directly to committed Git blobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_commit: str
    report_path: str
    report_sha256: str
    summary_path: str
    summary_sha256: str
    final_verdict: Literal["insufficient_evidence"]


class RunEvidenceBindingSummary(BaseModel):
    """One run whose current bytes, manifest entry, and evidence commit agree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    evidence_commit: str
    log_sha256: str
    summary_sha256: str


class ManualComparatorSummary(BaseModel):
    """Frozen manual comparator provenance and its validity limitation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence: RunEvidenceBindingSummary
    assembled_pair_count: int
    scored_pair_count: int
    valid_pair_count: int
    selected_step_index: int
    selected_state_a_index: int
    selected_valid_pair: bool


class SemifinalSubmissionSummary(BaseModel):
    """Machine-readable, no-new-simulation semifinal conclusion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    title: str
    scientific_question: str
    final_verdict: Literal["insufficient_evidence"]
    strongest_supported_claim: str
    prohibited_claims: tuple[str, ...]
    matrix: tuple[MatrixCellSummary, ...]
    total_proposal_attempts: int
    total_rejected_proposals: int
    total_accepted_pairs: int
    total_subprocess_curves: int
    total_valid_pairs: int
    valid_cells: int
    candidate: CandidateCardSummary
    effect_gate: EffectGateSummary
    instrument: InstrumentSummary
    archive: ArchiveSummary
    static_day6_context: CommittedStaticContextSummary
    manual_comparator: ManualComparatorSummary
    meander_r3_evidence: RunEvidenceBindingSummary
    rod_r2_evidence: RunEvidenceBindingSummary
    source_evidence_commit: str
    source_manifest_sha256: str
    candidate_freeze_commit: str
    frozen_candidates_sha256: str
    rod_r2_evidence_commit: str

    @model_validator(mode="after")
    def validate_claim_ceiling(self) -> Self:
        """Prevent a packaging change from upgrading the frozen conclusion."""

        if self.effect_gate.passed:
            raise ValueError("submission package must retain the failed effect gate")
        if self.instrument.candidate_openems_authorized:
            raise ValueError("submission package cannot authorize candidate openEMS")
        if self.instrument.candidate_openems_executed:
            raise ValueError("submission package cannot claim an unrun cross-check")
        if self.candidate.label != "paired-state computational hypothesis":
            raise ValueError("candidate label exceeds the frozen evidence")
        return self


class SubmissionDatasets(BaseModel):
    """Bounded rows used by the portable report and deterministic figures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    funnel: tuple[dict[str, str | int | float], ...]
    valid_cells: tuple[dict[str, str | int | float], ...]
    effect_gate: tuple[dict[str, str | int | float], ...]
    state_a_curves: tuple[dict[str, str | int | float], ...]
    state_b_curves: tuple[dict[str, str | int | float], ...]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_json_model(path: Path, model: type[BaseModel]) -> BaseModel:
    try:
        return model.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise SemifinalSubmissionError(f"cannot validate archived {path}: {error}") from error


def _manifest_entries_from_bytes(payload: bytes) -> tuple[SubmissionManifestEntry, ...]:
    try:
        entries = TypeAdapter(tuple[SubmissionManifestEntry, ...]).validate_json(
            payload
        )
    except ValueError as error:
        raise SemifinalSubmissionError(f"cannot validate archive manifest: {error}") from error
    run_ids = tuple(entry.run_id for entry in entries)
    if len(run_ids) != len(set(run_ids)):
        raise SemifinalSubmissionError("archive manifest contains duplicate run IDs")
    return entries


def _manifest_entries(repo_root: Path) -> tuple[SubmissionManifestEntry, ...]:
    path = repo_root / SUBMISSION_MANIFEST_PATH
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise SemifinalSubmissionError(f"cannot validate archive manifest: {error}") from error
    return _manifest_entries_from_bytes(payload)


def _validate_submission_manifest_successor(
    frozen_entries: Sequence[SubmissionManifestEntry],
    current_entries: Sequence[SubmissionManifestEntry],
) -> None:
    if len(frozen_entries) != SUBMISSION_MANIFEST_ENTRY_COUNT:
        raise SemifinalSubmissionError(
            "frozen submission manifest has an unexpected entry count"
        )
    if len(current_entries) < len(frozen_entries):
        raise SemifinalSubmissionError("current manifest is missing frozen submission entries")
    frozen_payloads = tuple(entry.model_dump(mode="json") for entry in frozen_entries)
    current_prefix = tuple(
        entry.model_dump(mode="json")
        for entry in current_entries[:SUBMISSION_MANIFEST_ENTRY_COUNT]
    )
    if current_prefix != frozen_payloads:
        raise SemifinalSubmissionError(
            "current manifest modified or reordered frozen submission entries"
        )


def _manifest_entry(
    entries: Sequence[SubmissionManifestEntry],
    run_id: str,
) -> SubmissionManifestEntry:
    matching = tuple(entry for entry in entries if entry.run_id == run_id)
    if len(matching) != 1:
        raise SemifinalSubmissionError(
            f"archive manifest must contain exactly one {run_id!r} entry"
        )
    return matching[0]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_show_bytes(repo_root: Path, commit: str, path: Path) -> bytes:
    try:
        process = subprocess.run(
            ("git", "show", f"{commit}:{path.as_posix()}"),
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise SemifinalSubmissionError(f"cannot execute Git evidence gate: {error}") from error
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise SemifinalSubmissionError(
            f"cannot read committed {commit}:{path.as_posix()}: {stderr}"
        )
    return process.stdout


def _require_committed_blob(
    repo_root: Path,
    commit: str,
    path: Path,
    expected_sha256: str,
) -> bytes:
    payload = _git_show_bytes(repo_root, commit, path)
    if _sha256_bytes(payload) != expected_sha256:
        raise SemifinalSubmissionError(
            f"committed blob SHA-256 drifted: {commit}:{path.as_posix()}"
        )
    return payload


def _require_run_evidence(
    repo_root: Path,
    entries: Sequence[SubmissionManifestEntry],
    run_id: str,
    evidence_commit: str,
    log_sha256: str,
    summary_sha256: str,
) -> RunEvidenceBindingSummary:
    expected = {"log.jsonl": log_sha256, "summary.json": summary_sha256}
    entry = _manifest_entry(entries, run_id)
    if entry.sha256 != expected:
        raise SemifinalSubmissionError(f"manifest evidence binding drifted: {run_id}")
    for name, digest in expected.items():
        path = Path("artifacts/runs") / run_id / name
        if _sha256_file(repo_root / path) != digest:
            raise SemifinalSubmissionError(f"current archive bytes drifted: {path.as_posix()}")
        _require_committed_blob(repo_root, evidence_commit, path, digest)
    return RunEvidenceBindingSummary(
        run_id=run_id,
        evidence_commit=evidence_commit,
        log_sha256=log_sha256,
        summary_sha256=summary_sha256,
    )


def _static_day6_context(repo_root: Path) -> CommittedStaticContextSummary:
    report = _require_committed_blob(
        repo_root, STATIC_DAY6_EVIDENCE_COMMIT, STATIC_DAY6_REPORT_PATH, STATIC_DAY6_REPORT_SHA256
    )
    if not report.startswith(b"# Day 6"):
        raise SemifinalSubmissionError("committed Day 6 report identity drifted")
    payload = _require_committed_blob(
        repo_root, STATIC_DAY6_EVIDENCE_COMMIT, STATIC_DAY6_SUMMARY_PATH, STATIC_DAY6_SUMMARY_SHA256
    )
    try:
        archived = StaticDay6ArchivedSummary.model_validate_json(payload)
    except ValueError as error:
        raise SemifinalSubmissionError(f"cannot validate committed Day 6 summary: {error}") from error
    return CommittedStaticContextSummary(
        evidence_commit=STATIC_DAY6_EVIDENCE_COMMIT,
        report_path=STATIC_DAY6_REPORT_PATH.as_posix(),
        report_sha256=STATIC_DAY6_REPORT_SHA256,
        summary_path=STATIC_DAY6_SUMMARY_PATH.as_posix(),
        summary_sha256=STATIC_DAY6_SUMMARY_SHA256,
        final_verdict=archived.final_verdict,
    )


def _verify_archive(
    artifacts_root: Path,
    entries: Sequence[SubmissionManifestEntry],
) -> tuple[bool, ...]:
    results: list[bool] = []
    for entry in entries:
        file_results: list[bool] = []
        for name in SUBMISSION_EVIDENCE_FILES:
            path = artifacts_root / entry.run_id / name
            try:
                actual = _sha256_file(path)
            except OSError:
                file_results.append(False)
            else:
                file_results.append(actual == entry.sha256[name])
        results.append(all(file_results))
    return tuple(results)


def _candidate_state(
    candidate: FrozenCategoryCandidate,
    state: Literal["A", "B"],
) -> CandidateStateSummary:
    control = candidate.proposal.state_a if state == "A" else candidate.proposal.state_b
    metrics = candidate.metrics.state_a if state == "A" else candidate.metrics.state_b
    geometry_hash = (
        candidate.state_a_geometry_hash if state == "A" else candidate.state_b_geometry_hash
    )
    return CandidateStateSummary(
        state=state,
        total_wire_length_mm=control.total_wire_length_um / 1000.0,
        span_ratio=control.span_ratio_ppm / 1_000_000.0,
        selected_frequency_ghz=metrics.selected_frequency_hz / 1e9,
        selected_s11_db=metrics.selected_s11_db,
        reflected_power_fraction=metrics.reflected_power_fraction,
        selected_index=metrics.selected_index,
        valid_internal_minimum=metrics.valid_search,
        geometry_hash=geometry_hash,
    )


def _candidate_card(candidate: FrozenCategoryCandidate) -> CandidateCardSummary:
    trajectory = candidate.trajectory
    if trajectory.minimum_clearance_m is None:
        raise SemifinalSubmissionError("frozen candidate trajectory metrics are incomplete")
    clearance = trajectory.minimum_clearance_m
    if trajectory.minimum_pitch_m is None:
        raise SemifinalSubmissionError("frozen candidate trajectory metrics are incomplete")
    pitch = trajectory.minimum_pitch_m
    if trajectory.minimum_height_m is None:
        raise SemifinalSubmissionError("frozen candidate trajectory metrics are incomplete")
    height = trajectory.minimum_height_m
    if trajectory.maximum_adjacent_node_displacement_m is None:
        raise SemifinalSubmissionError("frozen candidate trajectory metrics are incomplete")
    displacement = trajectory.maximum_adjacent_node_displacement_m
    hardware = candidate.proposal.hardware
    return CandidateCardSummary(
        label="paired-state computational hypothesis",
        source_run_id=candidate.source_run_id,
        source_step_index=candidate.source_step_index,
        source_proposal_index=candidate.source_proposal_index,
        hardware_hash=candidate.hardware_hash,
        pair_hash=candidate.pair_hash,
        mechanism_version=hardware.mechanism_version,
        box_size_mm=hardware.box_size_um / 1000.0,
        wire_radius_mm=hardware.wire_radius_um / 1000.0,
        turn_count=hardware.turn_count,
        feed_gap_ratio_ppm=hardware.feed_gap_ratio_ppm,
        terminal_ratio_ppm=hardware.terminal_ratio_ppm,
        physical_feed_gap_mm=hardware.box_size_um * hardware.feed_gap_ratio_ppm / 1_000_000_000.0,
        state_a=_candidate_state(candidate, "A"),
        state_b=_candidate_state(candidate, "B"),
        trajectory_point_count=trajectory.point_count,
        trajectory_valid=trajectory.valid,
        minimum_clearance_mm=1000.0 * clearance,
        minimum_pitch_mm=1000.0 * pitch,
        minimum_height_mm=1000.0 * height,
        maximum_adjacent_node_displacement_mm=1000.0 * displacement,
        source_log_sha256=candidate.source_log_sha256,
        source_summary_sha256=candidate.source_summary_sha256,
    )


def _load_selected_record(
    repo_root: Path,
    candidate: FrozenCategoryCandidate,
) -> PairedEvaluationRecord:
    path = repo_root / "artifacts/runs" / candidate.source_run_id / "log.jsonl"
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise SemifinalSubmissionError(f"cannot read candidate source log: {error}") from error
    if _sha256_bytes(payload) != candidate.source_log_sha256:
        raise SemifinalSubmissionError(f"candidate source log hash drifted: {candidate.source_run_id}")
    for line in payload.splitlines():
        if b'"event_type":"paired_evaluation"' not in line:
            continue
        record = PairedEvaluationRecord.model_validate_json(line)
        if record.step_index == candidate.source_step_index:
            if record.evaluation.pair_hash != candidate.pair_hash:
                raise SemifinalSubmissionError("selected record pair hash drifted")
            return record
    raise SemifinalSubmissionError(
        f"cannot find step {candidate.source_step_index} in {candidate.source_run_id}"
    )


def _matrix_rows(document: CandidateFreezeDocument) -> tuple[MatrixCellSummary, ...]:
    return tuple(
        MatrixCellSummary(
            agent=statistic.agent,
            seed=statistic.seed,
            accepted_pairs=statistic.accepted_pair_count,
            valid_pairs=statistic.valid_pair_count,
            rejected_proposals=statistic.rejected_proposals,
            proposal_attempts=statistic.proposal_attempts,
            subprocess_curves=statistic.subprocess_curve_count,
            wall_seconds=statistic.wall_seconds,
        )
        for statistic in document.agent_run_statistics
    )


def build_submission_summary(
    repo_root: Path,
) -> tuple[SemifinalSubmissionSummary, CandidateFreezeDocument]:
    """Recompute the semifinal package from archived evidence without a solver."""

    root = repo_root.resolve()
    document = build_candidate_freeze(root)
    if document.source_manifest_sha256 != SOURCE_MANIFEST_SHA256:
        raise SemifinalSubmissionError("historical source manifest binding drifted")
    _require_committed_blob(
        root,
        CANDIDATE_FREEZE_COMMIT,
        FROZEN_CANDIDATES_PATH,
        FROZEN_CANDIDATES_SHA256,
    )
    if _sha256_file(root / FROZEN_CANDIDATES_PATH) != FROZEN_CANDIDATES_SHA256:
        raise SemifinalSubmissionError("current frozen-candidates document drifted")
    static_day6_context = _static_day6_context(root)
    top_es = document.candidates[0]
    if top_es.category != "top-es" or not top_es.valid_pair_search:
        raise SemifinalSubmissionError("frozen top-ES candidate is not the expected valid object")
    manual_candidates = tuple(
        candidate for candidate in document.candidates if candidate.category == "manual-baseline"
    )
    if len(manual_candidates) != 1:
        raise SemifinalSubmissionError("frozen manual comparator is not unique")
    manual_candidate = manual_candidates[0]

    manual_summary = _read_json_model(
        root / "artifacts/runs" / MANUAL_BASELINE_RUN_ID / "summary.json",
        ManualBaselineRunSummary,
    )
    if not isinstance(manual_summary, ManualBaselineRunSummary):
        raise SemifinalSubmissionError("manual summary model dispatch failed")
    rod_summary = _read_json_model(
        root / "artifacts/runs" / ROD_R2_RUN_ID / "summary.json",
        RodR2Summary,
    )
    if not isinstance(rod_summary, RodR2Summary):
        raise SemifinalSubmissionError("rod-r2 summary model dispatch failed")
    meander_summary = _read_json_model(
        root / "artifacts/runs" / MEANDER_R3_RUN_ID / "summary.json",
        MeanderR3Summary,
    )
    if not isinstance(meander_summary, MeanderR3Summary):
        raise SemifinalSubmissionError("meander-r3 summary model dispatch failed")

    frozen_manifest_payload = _require_committed_blob(
        root,
        ROD_R2_EVIDENCE_COMMIT,
        SUBMISSION_MANIFEST_PATH,
        SUBMISSION_MANIFEST_SHA256,
    )
    entries = _manifest_entries_from_bytes(frozen_manifest_payload)
    current_entries = _manifest_entries(root)
    _validate_submission_manifest_successor(entries, current_entries)
    manual_evidence = _require_run_evidence(
        root,
        entries,
        MANUAL_BASELINE_RUN_ID,
        MANUAL_BASELINE_EVIDENCE_COMMIT,
        MANUAL_BASELINE_LOG_SHA256,
        MANUAL_BASELINE_SUMMARY_SHA256,
    )
    meander_evidence = _require_run_evidence(
        root,
        entries,
        MEANDER_R3_RUN_ID,
        MEANDER_R3_EVIDENCE_COMMIT,
        MEANDER_R3_LOG_SHA256,
        MEANDER_R3_SUMMARY_SHA256,
    )
    rod_evidence = _require_run_evidence(
        root,
        entries,
        ROD_R2_RUN_ID,
        ROD_R2_EVIDENCE_COMMIT,
        ROD_R2_LOG_SHA256,
        ROD_R2_SUMMARY_SHA256,
    )
    if (
        manual_summary.pair_total != 5_184
        or manual_summary.scored_pairs != 756
        or manual_summary.valid_pair_count != 0
        or manual_candidate.source_step_index != 288
        or manual_candidate.metrics.state_a.selected_index != 100
        or manual_candidate.valid_pair_search
    ):
        raise SemifinalSubmissionError("manual comparator counts or validity drifted")
    archive_results = _verify_archive(root / "artifacts/runs", entries)
    archive_ok = sum(1 for result in archive_results if result)
    matrix = _matrix_rows(document)
    effect = document.effect_assessment
    repair = rod_summary.repair_diagnostic
    summary = SemifinalSubmissionSummary(
        title=REPORT_TITLE,
        scientific_question=(
            "Can one ideal telescopic PEC meander in a 40 mm box use two actuator "
            "states to serve 2.45 GHz and 5.8 GHz while reducing the worse-state "
            "reflected power by at least 10% versus the frozen manual comparator "
            "within a frozen search space, budget, and seed set?"
        ),
        final_verdict="insufficient_evidence",
        strongest_supported_claim=(
            "Within the frozen search space, budget, and seed set, YAF found one "
            "NEC2-valid, 21-point-audited paired-state computational hypothesis, but "
            "the 4.674% descriptive reduction missed the frozen 10% effect gate, "
            "cross-seed stability was not established, and independent openEMS "
            "confirmation was not authorized."
        ),
        prohibited_claims=(
            "invented a new antenna",
            "YAF-M1",
            "confirmed improvement",
            "dual-solver confirmed",
            "manufacturable autonomous adaptive antenna",
            "ES was stable across seeds",
            "continuous motion was validated",
            "static dual-band operation is impossible",
            "the frozen manual comparator is the strongest baseline",
        ),
        matrix=matrix,
        total_proposal_attempts=sum(item.proposal_attempts for item in matrix),
        total_rejected_proposals=sum(item.rejected_proposals for item in matrix),
        total_accepted_pairs=sum(item.accepted_pairs for item in matrix),
        total_subprocess_curves=sum(item.subprocess_curves for item in matrix),
        total_valid_pairs=sum(item.valid_pairs for item in matrix),
        valid_cells=sum(item.valid_pairs > 0 for item in matrix),
        candidate=_candidate_card(top_es),
        effect_gate=EffectGateSummary(
            metric=effect.metric,
            candidate_value=effect.candidate_value,
            manual_reference_value=effect.reference_value,
            maximum_allowed_value=(
                effect.maximum_candidate_to_reference_ratio * effect.reference_value
            ),
            observed_reduction_fraction=effect.relative_reduction_fraction,
            required_reduction_fraction=effect.threshold_fraction,
            passed=effect.passed,
        ),
        instrument=InstrumentSummary(
            thin_box_r3_run_id=meander_summary.run_id,
            thin_box_r3_verdict=meander_summary.decision.verdict,
            thin_box_r3_anchor_released=meander_summary.decision.anchor_released,
            thin_box_r3_frequency_gap_fraction=(
                meander_summary.decision.cross_solver_decision.resonance_relative_difference
            ),
            thin_box_r3_pearson=(
                meander_summary.decision.cross_solver_decision.curve_pearson_correlation
            ),
            thin_box_r3_last_shift_fraction=(
                meander_summary.decision.openems_16x_to_32x_resonance_shift
            ),
            rod_r2_run_id=rod_summary.run_id,
            rod_r2_result_status=rod_summary.result_status,
            rod_r2_repair_gate_passed=repair.gate_passed,
            rod_r2_failure_reasons=repair.failure_reasons,
            rod_r2_repaired_voltage_probe_exists=(repair.repaired_b.voltage_probe.exists),
            rod_r2_repaired_voltage_samples=(
                repair.repaired_b.voltage_probe.parseable_sample_count
            ),
            rod_r2_repaired_current_probe_exists=(repair.repaired_b.current_probe.exists),
            rod_r2_repaired_current_samples=(
                repair.repaired_b.current_probe.parseable_sample_count
            ),
            candidate_openems_authorized=document.openems_cross_check_authorized,
            candidate_openems_executed=False,
        ),
        archive=ArchiveSummary(
            manifest_entry_count=len(entries),
            verified_ok_count=archive_ok,
            manifest_sha256=_sha256_bytes(frozen_manifest_payload),
            all_ok=archive_ok == len(entries),
        ),
        static_day6_context=static_day6_context,
        manual_comparator=ManualComparatorSummary(
            evidence=manual_evidence,
            assembled_pair_count=manual_summary.pair_total,
            scored_pair_count=manual_summary.scored_pairs,
            valid_pair_count=manual_summary.valid_pair_count,
            selected_step_index=manual_candidate.source_step_index,
            selected_state_a_index=manual_candidate.metrics.state_a.selected_index,
            selected_valid_pair=manual_candidate.valid_pair_search,
        ),
        meander_r3_evidence=meander_evidence,
        rod_r2_evidence=rod_evidence,
        source_evidence_commit=document.source_evidence_commit,
        source_manifest_sha256=document.source_manifest_sha256,
        candidate_freeze_commit=CANDIDATE_FREEZE_COMMIT,
        frozen_candidates_sha256=FROZEN_CANDIDATES_SHA256,
        rod_r2_evidence_commit=ROD_R2_EVIDENCE_COMMIT,
    )
    return summary, document


def _curve_rows(
    repo_root: Path,
    candidates: Sequence[FrozenCategoryCandidate],
    state: Literal["A", "B"],
) -> tuple[dict[str, str | int | float], ...]:
    rows: list[dict[str, str | int | float]] = []
    for candidate in candidates:
        record = _load_selected_record(repo_root, candidate)
        curve = record.evaluation.state_a_curve if state == "A" else record.evaluation.state_b_curve
        for frequency, s11 in zip(curve.frequency_hz, curve.s11_db, strict=True):
            rows.append(
                {
                    "category": candidate.category,
                    "frequency_ghz": frequency / 1e9,
                    "s11_db": s11,
                    "valid_pair": int(candidate.valid_pair_search),
                    "source_run_id": candidate.source_run_id,
                    "source_step": candidate.source_step_index,
                }
            )
    return tuple(rows)


def build_submission_datasets(
    repo_root: Path,
    summary: SemifinalSubmissionSummary,
    document: CandidateFreezeDocument,
) -> SubmissionDatasets:
    """Build bounded, reviewed report datasets from the validated summary."""

    return SubmissionDatasets(
        funnel=(
            {"ordinal": 1, "stage": "Proposal attempts", "count": summary.total_proposal_attempts},
            {"ordinal": 2, "stage": "Geometry accepted", "count": summary.total_accepted_pairs},
            {"ordinal": 3, "stage": "NEC2-valid pairs", "count": summary.total_valid_pairs},
            {"ordinal": 4, "stage": "Positive-eligible frozen hypotheses", "count": 1},
            {"ordinal": 5, "stage": "Positive verdicts", "count": 0},
        ),
        valid_cells=tuple(
            {
                "agent": item.agent,
                "seed": item.seed,
                "cell": f"{item.agent} / {item.seed}",
                "valid_pairs": item.valid_pairs,
                "accepted_pairs": item.accepted_pairs,
                "valid_fraction": item.valid_pairs / item.accepted_pairs,
            }
            for item in summary.matrix
        ),
        effect_gate=(
            {
                "ordinal": 1,
                "quantity": "Candidate L",
                "reflected_power_fraction": summary.effect_gate.candidate_value,
            },
            {
                "ordinal": 2,
                "quantity": "Required maximum",
                "reflected_power_fraction": summary.effect_gate.maximum_allowed_value,
            },
            {
                "ordinal": 3,
                "quantity": "Manual reference L",
                "reflected_power_fraction": summary.effect_gate.manual_reference_value,
            },
        ),
        state_a_curves=_curve_rows(repo_root, document.candidates, "A"),
        state_b_curves=_curve_rows(repo_root, document.candidates, "B"),
    )


def _sql_values(
    rows: Sequence[dict[str, str | int | float]],
    fields: Sequence[str],
) -> str:
    """Return a runnable VALUES query that exactly reproduces bounded chart rows."""

    def sql_literal(value: str | int | float) -> str:
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        if isinstance(value, float):
            if not math.isfinite(value):
                raise SemifinalSubmissionError("non-finite chart value")
            return repr(value)
        return str(value)

    values = ",\n  ".join(
        "(" + ", ".join(sql_literal(row[field]) for field in fields) + ")" for row in rows
    )
    columns = ", ".join(fields)
    return f"SELECT * FROM (VALUES\n  {values}\n) AS t({columns})"


def _source(
    source_id: str,
    label: str,
    path: str,
    rows: Sequence[dict[str, str | int | float]],
    fields: Sequence[str],
    metric_definitions: Sequence[str],
    paths: Sequence[str] | None = None,
) -> dict[str, object]:
    tables_used = tuple(paths) if paths is not None else (path,)
    return {
        "id": source_id,
        "label": label,
        "path": path,
        "paths": list(tables_used),
        "query": {
            "sql": _sql_values(rows, fields),
            "description": "Exact bounded rows derived by scripts/semifinal_demo.py from archived evidence.",
            "engine": "portable-snapshot",
            "language": "sql",
            "tables_used": list(tables_used),
            "metric_definitions": list(metric_definitions),
        },
    }


def _markdown_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_candidate_card(summary: SemifinalSubmissionSummary) -> bytes:
    """Render the reviewer-facing hypothesis card with an explicit claim ceiling."""

    card = summary.candidate
    state_rows = (
        (
            "A",
            f"{card.state_a.total_wire_length_mm:.3f}",
            f"{card.state_a.span_ratio:.6f}",
            f"{card.state_a.selected_frequency_ghz:.4f}",
            f"{card.state_a.selected_s11_db:.3f}",
            str(card.state_a.selected_index),
            str(card.state_a.valid_internal_minimum),
            f"{1.0 - card.state_a.reflected_power_fraction:.6f}",
            card.state_a.geometry_hash,
        ),
        (
            "B",
            f"{card.state_b.total_wire_length_mm:.3f}",
            f"{card.state_b.span_ratio:.6f}",
            f"{card.state_b.selected_frequency_ghz:.4f}",
            f"{card.state_b.selected_s11_db:.3f}",
            str(card.state_b.selected_index),
            str(card.state_b.valid_internal_minimum),
            f"{1.0 - card.state_b.reflected_power_fraction:.6f}",
            card.state_b.geometry_hash,
        ),
    )
    lines = [
        "# Paired-state computational hypothesis card",
        "",
        "> Status: `NEC2-only / insufficient_evidence`. This is not YAF-M1, a confirmed",
        "> invention, a manufacturable antenna, or a continuous-motion proof.",
        "",
        f"- Source: `{card.source_run_id}`, step `{card.source_step_index}`, proposal `{card.source_proposal_index}`",
        f"- Hardware hash: `{card.hardware_hash}`",
        f"- Pair hash: `{card.pair_hash}`",
        f"- Mechanism: `{card.mechanism_version}`",
        f"- Box / wire radius: `{card.box_size_mm:.1f} mm` / `{card.wire_radius_mm:.3f} mm`",
        f"- Turns / feed-gap ppm / terminal ppm: `{card.turn_count}` / `{card.feed_gap_ratio_ppm}` / `{card.terminal_ratio_ppm}`",
        f"- Physical feed gap: `{card.physical_feed_gap_mm:.6f} mm`",
        f"- Minimum pitch / height: `{card.minimum_pitch_mm:.6f} mm` / `{card.minimum_height_mm:.6f} mm`",
        f"- Maximum adjacent trajectory movement: `{card.maximum_adjacent_node_displacement_mm:.6f} mm`",
        "",
        _markdown_table(
            ("State", "Wire length (mm)", "Span ratio", "Selected GHz", "S11 (dB)", "Index", "Internal valid", "State FoM", "Geometry SHA-256"),
            state_rows,
        ),
        "",
        "The frozen valid-index interval is 3..97 inclusive. State A index 93 and state B",
        "index 7 are each four bins inside the nearest validity boundary and are therefore",
        "valid but edge-adjacent observations.",
        "",
        f"The {card.trajectory_point_count}-point discrete trajectory passed. Minimum clearance was "
        f"{card.minimum_clearance_mm:.6f} mm, only "
        f"{1000.0 * (card.minimum_clearance_mm - 0.2):.3f} um above the frozen 0.200 mm boundary.",
        "",
        f"The candidate reduced the worse-state reflected-power fraction by "
        f"{100.0 * summary.effect_gate.observed_reduction_fraction:.6f}% versus the frozen "
        f"manual comparator, below the preregistered {100.0 * summary.effect_gate.required_reduction_fraction:.1f}% requirement.",
        "",
        f"Manual-comparator limitation: {summary.manual_comparator.assembled_pair_count:,} pairs were assembled, "
        f"{summary.manual_comparator.scored_pair_count} were scored, and {summary.manual_comparator.valid_pair_count} "
        f"were valid. Its selected state-A minimum was index {summary.manual_comparator.selected_state_a_index} "
        "(the sweep endpoint), so this comparator was nonvalid and is not claimed to be the strongest possible baseline.",
        "",
        "Independent openEMS candidate confirmation was not authorized because the 5.8 GHz rod",
        "instrument was `NOT RELEASED` (`repair_not_confirmed`); the repaired probes existed but carried zero",
        "parseable samples in the frozen diagnostic run.",
        "",
        "Model exclusions: sleeve overlap, contact resistance, actuator volume, mechanical stress,",
        "conductor loss, tolerance robustness, and continuous-path mechanics.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def render_evidence_index(summary: SemifinalSubmissionSummary) -> bytes:
    """Map each submission claim to exact archived evidence."""

    card = summary.candidate
    rows = (
        (
            "Historical static Day 6 study ended insufficient_evidence",
            f"{summary.static_day6_context.report_path} + {summary.static_day6_context.summary_path}",
            "committed blobs",
            summary.static_day6_context.evidence_commit,
            f"report={summary.static_day6_context.report_sha256}; summary={summary.static_day6_context.summary_sha256}",
        ),
        (
            "Manual comparator: 5,184 assembled / 756 scored / 0 valid",
            summary.manual_comparator.evidence.run_id,
            f"selected step {summary.manual_comparator.selected_step_index}; A index {summary.manual_comparator.selected_state_a_index}",
            summary.manual_comparator.evidence.evidence_commit,
            f"log={summary.manual_comparator.evidence.log_sha256}; summary={summary.manual_comparator.evidence.summary_sha256}",
        ),
        (
            "9-cell paired search historical source manifest",
            "semifinal-paired-{random,es-cold,es-warm}-s{101,202,303}",
            "all accepted steps",
            summary.source_evidence_commit,
            summary.source_manifest_sha256,
        ),
        (
            "Selected ES source curve bytes",
            card.source_run_id,
            str(card.source_step_index),
            summary.source_evidence_commit,
            f"log={card.source_log_sha256}; summary={card.source_summary_sha256}",
        ),
        (
            "Selected Random source curve bytes",
            RANDOM_SOURCE_RUN_ID,
            "130",
            summary.source_evidence_commit,
            f"log={RANDOM_SOURCE_LOG_SHA256}; summary={RANDOM_SOURCE_SUMMARY_SHA256}",
        ),
        (
            "Frozen candidate selection and 4.674% effect-gate result",
            FROZEN_CANDIDATES_PATH.as_posix(),
            "top-es / top-random / manual-baseline",
            summary.candidate_freeze_commit,
            summary.frozen_candidates_sha256,
        ),
        (
            "Thin-box 5.8 GHz anchor not released",
            summary.instrument.thin_box_r3_run_id,
            "all seven steps",
            summary.meander_r3_evidence.evidence_commit,
            f"log={summary.meander_r3_evidence.log_sha256}; summary={summary.meander_r3_evidence.summary_sha256}",
        ),
        (
            "Rod repair gate not confirmed; no science ladder",
            summary.instrument.rod_r2_run_id,
            "A/B diagnostics only",
            summary.rod_r2_evidence.evidence_commit,
            f"log={summary.rod_r2_evidence.log_sha256}; summary={summary.rod_r2_evidence.summary_sha256}",
        ),
        (
            f"Full archive integrity {summary.archive.verified_ok_count}/{summary.archive.manifest_entry_count}",
            "artifacts/runs/manifest.json",
            "all entries",
            summary.rod_r2_evidence_commit,
            summary.archive.manifest_sha256,
        ),
    )
    lines = [
        "# Semifinal evidence index",
        "",
        _markdown_table(
            ("Claim", "Run ID / source", "Step", "Commit", "Digest / artifact"),
            rows,
        ),
        "",
        "The paired candidate freeze at `4a8222e` binds the frozen-candidates document only.",
        "The historical 218-entry source manifest is separately pinned at `a19684b` by its",
        "canonical content digest. The current 219-entry manifest is an append-safe successor:",
        "every pinned canonical JSON entry must remain identical after canonical JSON serialization,",
        "every pinned source file must remain byte-identical, and only unique entries may be",
        "appended.",
        "Day 6 report/summary digests above are hashes of committed Git blobs, not CRLF working-tree views.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def render_report_markdown(summary: SemifinalSubmissionSummary) -> bytes:
    """Render the long-form technical report source."""

    matrix_rows = tuple(
        (
            item.agent,
            str(item.seed),
            str(item.accepted_pairs),
            str(item.valid_pairs),
            f"{100.0 * item.valid_pairs / item.accepted_pairs:.2f}%",
            str(item.rejected_proposals),
        )
        for item in summary.matrix
    )
    gate_rows = (
        ("Shared hardware hash", "PASS", summary.candidate.hardware_hash),
        ("Distinct A/B geometry", "PASS", "state hashes differ"),
        ("21-point discrete trajectory", "PASS", f"clearance {summary.candidate.minimum_clearance_mm:.6f} mm"),
        ("NEC2 state A internal minimum and S11<=-6 dB", "PASS", f"{summary.candidate.state_a.selected_frequency_ghz:.4f} GHz / {summary.candidate.state_a.selected_s11_db:.3f} dB"),
        ("NEC2 state B internal minimum and S11<=-6 dB", "PASS", f"{summary.candidate.state_b.selected_frequency_ghz:.4f} GHz / {summary.candidate.state_b.selected_s11_db:.3f} dB"),
        ("Reflected-power reduction >=10%", "FAIL", f"{100.0 * summary.effect_gate.observed_reduction_fraction:.6f}%"),
        ("Cross-seed stability", "NOT ESTABLISHED", f"{summary.valid_cells}/9 cells valid"),
        ("Manual comparator validity", "NOT VALID", "0/5,184 assembled pairs valid; selected A index 100"),
        ("5.8 GHz openEMS rod instrument", "NOT RELEASED", summary.instrument.rod_r2_result_status),
        ("Candidate openEMS cross-check", "NOT AUTHORIZED", "not run"),
        ("Continuous mechanics / manufacturing", "OUT OF SCOPE", "ideal PEC model only"),
    )
    lines = [
        f"# {summary.title}",
        "",
        "## Technical summary",
        "",
        summary.strongest_supported_claim,
        "",
        f"The final verdict is `{summary.final_verdict}`. The scientific asset is a source-addressed,",
        "falsifiable hypothesis plus an auditable explanation of why it was not upgraded to a discovery.",
        "",
        "## Key findings",
        "",
        f"The frozen matrix executed {summary.total_accepted_pairs:,} paired evaluations and "
        f"{summary.total_subprocess_curves:,} real NEC2 subprocess curves. Geometry validation rejected "
        f"{summary.total_rejected_proposals:,} proposals before they could spend accepted budget. Only "
        f"{summary.total_valid_pairs} valid pairs appeared, all in one of nine cells.",
        "",
        _markdown_table(("Agent", "Seed", "Accepted", "Valid", "Valid rate", "Rejected"), matrix_rows),
        "",
        f"The prior static Day 6 study is historical context bound to commit "
        f"`{summary.static_day6_context.evidence_commit}`; its committed summary verdict was "
        "`insufficient_evidence`. It supports only a bounded negative result within its frozen "
        "search space, budget, and seed set. It does not show that static dual-band operation is "
        "impossible.",
        "",
        "A raw-score leader appeared to improve the manual reference by 20.583%, but its two minima",
        "were at sweep endpoints and the preregistered internal-minimum gate excluded it. The frozen",
        "validity-first candidate improved the worse-state reflected-power fraction by only 4.674341%.",
        "",
        "## Candidate and gate ledger",
        "",
        f"The manual comparator assembled {summary.manual_comparator.assembled_pair_count:,} pairs, "
        f"scored {summary.manual_comparator.scored_pair_count}, and produced "
        f"{summary.manual_comparator.valid_pair_count} valid pairs. Its selected A minimum was index "
        f"{summary.manual_comparator.selected_state_a_index}, so it is a frozen diagnostic comparator, not a strongest-baseline claim.",
        _markdown_table(("Gate", "Status", "Evidence"), gate_rows),
        "",
        "## Instrument outcome",
        "",
        f"The terminal thin-box anchor reached {100.0 * summary.instrument.thin_box_r3_last_shift_fraction:.3f}% "
        f"last-step movement, {100.0 * summary.instrument.thin_box_r3_frequency_gap_fraction:.3f}% "
        f"NEC2/openEMS frequency gap, and Pearson {summary.instrument.thin_box_r3_pearson:.6f}, but its "
        "32x minimum was just above the frozen band edge, so the anchor was not released.",
        "",
        "The bounded rod-renderer repair then produced both repaired probe files but zero parseable",
        "samples. The instrument was NOT RELEASED before NEC2 or the openEMS science ladder could",
        "run. This is an instrument failure record, not evidence for or against the candidate geometry.",
        "",
        "## Scope, data, and metric definitions",
        "",
        "The search object is one shared, quantized ideal telescopic PEC meander hardware identity",
        "with two actuator states. State A targets 2.40-2.50 GHz; state B targets 5.725-5.875 GHz.",
        "For each state, L=10^(S11/10) and state FoM=1-L. The paired base_score is",
        "min(FoM_A,FoM_B)=1-max(L_A,L_B). The effect gate is a separate comparison of",
        "max(L_A,L_B): it requires max(L_candidate)<=0.90*max(L_manual) in the NEC2",
        "reference instrument. A high base_score is therefore not itself an effect-gate pass.",
        "",
        "Search validity additionally requires S11<=-6 dB and selected index 3..97 inclusive.",
        f"The frozen candidate uses A index {summary.candidate.state_a.selected_index} and B index "
        f"{summary.candidate.state_b.selected_index}; each is four bins inside the nearest edge guard.",
        "",
        "## Methodology and reproducibility",
        "",
        "Candidates were selected from archived JSONL only after the 9-cell matrix completed. Selection",
        "was validity-first, then score, then deterministic hash/run/step tie-breakers. The freeze",
        "recomputes metrics, geometry hashes, the pair hash, and the 21-point trajectory from committed",
        "source bytes. `scripts/semifinal_demo.py --verify` performs this reconstruction and verifies",
        "the full SHA-256 archive without invoking any solver.",
        "",
        "## Limitations and uncertainty",
        "",
        "Only ES-warm seed 101 produced valid pairs; cross-seed stability was not established. The candidate's",
        "minimum clearance is only 2.752 um above the frozen boundary. Realized gain, lambda/40 effect",
        "direction, continuous motion, material loss, sleeve overlap, contact resistance, stress,",
        "actuator volume, and manufacturing tolerance were not established. Independent openEMS",
        "candidate curves do not exist because the instrument gate blocked them. The manual comparator",
        "was nonvalid and is not evidence that it is the strongest achievable baseline.",
        "",
        "## Recommended next steps",
        "",
        "1. Treat the current object as a hypothesis-library entry, not a discovery.",
        "2. Start a new preregistered study around the sparse warm-101 feasible region with robustness",
        "   and clearance margins in the objective; do not alter this batch retrospectively.",
        "3. Any future rod repair must be a separate preregistered study; no rod-r3 is authorized in",
        "   this submission cycle. Release a 5.8 GHz port instrument before any candidate cross-check.",
        "4. Add lossy telescoping contacts and actuator geometry, then fabricate and measure only after",
        "   the simulation gate chain passes.",
        "",
        "## Further research question",
        "",
        "Can a prospectively registered robust search find this paired-state feasible region across",
        "multiple seeds while passing the unchanged 10% effect gate and an independently released",
        "openEMS instrument?",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def build_portable_artifact(
    summary: SemifinalSubmissionSummary,
    datasets: SubmissionDatasets,
) -> dict[str, object]:
    """Build a canonical report artifact for the portable HTML packager."""

    frozen_path = FROZEN_CANDIDATES_PATH.as_posix()
    source_funnel = _source(
        "frozen-funnel",
        "Frozen paired-state candidate evidence",
        frozen_path,
        datasets.funnel,
        ("ordinal", "stage", "count"),
        ("count is the exact number of proposals remaining at each audited stage.",),
    )
    source_cells = _source(
        "frozen-cells",
        "Frozen 3-by-3 agent matrix",
        frozen_path,
        datasets.valid_cells,
        ("agent", "seed", "cell", "valid_pairs", "accepted_pairs", "valid_fraction"),
        ("valid_fraction=valid_pairs/accepted_pairs for one frozen agent-seed cell.",),
    )
    source_effect = _source(
        "frozen-effect",
        "Preregistered reflected-power gate",
        frozen_path,
        datasets.effect_gate,
        ("ordinal", "quantity", "reflected_power_fraction"),
        ("state FoM=1-L; base_score=1-max(L_A,L_B); the effect gate compares max(L).",),
    )
    curve_run_ids = tuple(
        dict.fromkeys(str(row["source_run_id"]) for row in datasets.state_a_curves)
    )
    curve_paths = tuple(
        f"artifacts/runs/{run_id}/log.jsonl" for run_id in curve_run_ids
    )
    curve_root = "artifacts/runs"
    source_a = _source(
        "state-a-curves",
        "Frozen state-A source curves",
        curve_root,
        datasets.state_a_curves,
        ("category", "frequency_ghz", "s11_db", "valid_pair", "source_run_id", "source_step"),
        ("S11 is reported in dB on the frozen 2.40-2.50 GHz NEC2 sweep.",),
        paths=curve_paths,
    )
    source_b = _source(
        "state-b-curves",
        "Frozen state-B source curves",
        curve_root,
        datasets.state_b_curves,
        ("category", "frequency_ghz", "s11_db", "valid_pair", "source_run_id", "source_step"),
        ("S11 is reported in dB on the frozen 5.725-5.875 GHz NEC2 sweep.",),
        paths=curve_paths,
    )
    sources = [source_funnel, source_cells, source_effect, source_a, source_b]
    title = "YAF GOAI semifinal evidence report"
    manifest: dict[str, object] = {
        "version": 1,
        "surface": "report",
        "title": title,
        "description": "A solver-free, source-bound account of the paired-state semifinal study.",
        "blocks": [
            {"id": "title", "type": "markdown", "body": f"# {title}"},
            {
                "id": "summary",
                "type": "markdown",
                "body": (
                    "## Technical summary\n\n"
                    + summary.strongest_supported_claim
                    + f"\n\nFinal verdict: `{summary.final_verdict}`."
                ),
            },
            {"id": "funnel-heading", "type": "markdown", "body": "## Exploration funnel"},
            {"id": "funnel-block", "type": "chart", "chartId": "funnel-chart"},
            {"id": "cells-heading", "type": "markdown", "body": "## Valid paired designs across the 3 x 3 matrix"},
            {"id": "cells-block", "type": "chart", "chartId": "cells-chart"},
            {"id": "effect-heading", "type": "markdown", "body": "## Preregistered effect gate"},
            {"id": "effect-block", "type": "chart", "chartId": "effect-chart"},
            {"id": "curves-heading", "type": "markdown", "body": "## Frozen NEC2 comparison curves"},
            {"id": "state-a-block", "type": "chart", "chartId": "state-a-chart"},
            {"id": "state-b-block", "type": "chart", "chartId": "state-b-chart"},
            {
                "id": "instrument",
                "type": "markdown",
                "body": (
                    "## Independent-instrument outcome\n\n"
                    "The thin-box anchor was NOT RELEASED (`not_released_out_of_band_high`). The "
                    "bounded rod-r2 repair gate was NOT RELEASED (`repair_not_confirmed`): probe files "
                    "existed but each had zero parseable samples. Candidate openEMS confirmation "
                    "was therefore not authorized or run."
                ),
            },
            {
                "id": "limitations",
                "type": "markdown",
                "body": (
                    "## Limitations and next action\n\n"
                    "The candidate is a NEC2-only computational hypothesis. Only ES-warm seed 101 "
                    "produced valid pairs; cross-seed stability was not established. The 10% effect "
                    "gate failed, the manual comparator was nonvalid, clearance margin was only 2.752 um, and continuous "
                    "mechanics, loss, contacts, actuation, manufacturing, realized gain, and cross-solver "
                    "candidate curves remain unestablished. Any future repair must be separately "
                    "preregistered; no rod-r3 is authorized in this submission cycle."
                ),
            },
        ],
        "charts": [
            {
                "id": "funnel-chart",
                "title": "Audited exploration stages",
                "subtitle": "6,210 attempts narrowed to one positive-eligible frozen hypothesis and zero positive verdicts.",
                "type": "bar",
                "dataset": "funnel",
                "source": source_funnel,
                "encodings": {
                    "x": {"field": "stage", "type": "nominal"},
                    "y": {"field": "count", "type": "quantitative"},
                },
                "options": {"orientation": "horizontal"},
            },
            {
                "id": "cells-chart",
                "title": "NEC2-valid paired designs per frozen agent-seed cell",
                "subtitle": "Only ES-warm seed 101 produced valid pairs; cross-seed stability was not established.",
                "type": "bar",
                "dataset": "valid_cells",
                "source": source_cells,
                "encodings": {
                    "x": {"field": "cell", "type": "nominal"},
                    "y": {"field": "valid_pairs", "type": "quantitative"},
                },
            },
            {
                "id": "effect-chart",
                "title": "Worst-state reflected-power fraction",
                "subtitle": "Candidate L remained above the preregistered maximum; lower is better.",
                "type": "bar",
                "dataset": "effect_gate",
                "source": source_effect,
                "encodings": {
                    "x": {"field": "quantity", "type": "nominal"},
                    "y": {"field": "reflected_power_fraction", "type": "quantitative"},
                },
            },
            {
                "id": "state-a-chart",
                "title": "State A NEC2 S11 curves",
                "subtitle": "2.40-2.50 GHz; only the frozen ES candidate has a valid internal minimum.",
                "type": "line",
                "dataset": "state_a_curves",
                "source": source_a,
                "encodings": {
                    "x": {"field": "frequency_ghz", "type": "quantitative"},
                    "y": {"field": "s11_db", "type": "quantitative"},
                    "color": {"field": "category", "type": "nominal"},
                },
            },
            {
                "id": "state-b-chart",
                "title": "State B NEC2 S11 curves",
                "subtitle": "5.725-5.875 GHz; validity requires an internal minimum and S11 <= -6 dB.",
                "type": "line",
                "dataset": "state_b_curves",
                "source": source_b,
                "encodings": {
                    "x": {"field": "frequency_ghz", "type": "quantitative"},
                    "y": {"field": "s11_db", "type": "quantitative"},
                    "color": {"field": "category", "type": "nominal"},
                },
            },
        ],
        "sources": sources,
    }
    snapshot: dict[str, object] = {
        "version": 1,
        "status": "ready",
        "datasets": datasets.model_dump(mode="json"),
    }
    return {
        "surface": "report",
        "manifest": manifest,
        "snapshot": snapshot,
        "sources": sources,
    }


def _geometry_path(geometry_vertices: Sequence[Sequence[float]], faces: Sequence[Sequence[int]]) -> tuple[int, ...]:
    adjacency: dict[int, list[int]] = {index: [] for index in range(len(geometry_vertices))}
    for edge in faces:
        if len(edge) != 2:
            raise SemifinalSubmissionError("geometry display requires two-node edges")
        left, right = edge
        adjacency[left].append(right)
        adjacency[right].append(left)
    endpoints = sorted(index for index, neighbours in adjacency.items() if len(neighbours) == 1)
    if len(endpoints) != 2:
        raise SemifinalSubmissionError("geometry display path is not one connected polyline")
    output = [endpoints[0]]
    previous: int | None = None
    current = endpoints[0]
    while current != endpoints[1]:
        next_nodes = [node for node in adjacency[current] if node != previous]
        if len(next_nodes) != 1:
            raise SemifinalSubmissionError("geometry display path has a branch")
        previous, current = current, next_nodes[0]
        output.append(current)
    if len(output) != len(geometry_vertices):
        raise SemifinalSubmissionError("geometry display path omitted vertices")
    return tuple(output)


def _interpolate_integer(start: int, end: int, index: int, count: int = 21) -> int:
    numerator = (count - 1 - index) * start + index * end
    return (numerator + (count - 1) // 2) // (count - 1)


def _trajectory_geometries(proposal: PairedProposal) -> tuple[Geometry, ...]:
    geometries: list[Geometry] = []
    for index in range(21):
        length_um = _interpolate_integer(
            proposal.state_a.total_wire_length_um,
            proposal.state_b.total_wire_length_um,
            index,
        )
        span_ppm = _interpolate_integer(
            proposal.state_a.span_ratio_ppm,
            proposal.state_b.span_ratio_ppm,
            index,
        )
        geometry = _build_quantized_geometry(
            proposal.hardware,
            length_um,
            span_ppm,
            f"display_{index:02d}",
        )
        geometries.append(geometry)
    return tuple(geometries)


def write_geometry_assets(
    repo_root: Path,
    document: CandidateFreezeDocument,
    output_directory: Path,
) -> None:
    """Render deterministic display-only PNG/GIF assets from the frozen proposal."""

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import PillowWriter

    proposal = document.candidates[0].proposal
    geometries = _trajectory_geometries(proposal)
    endpoint_geometries = (geometries[0], geometries[-1])
    from matplotlib.artist import Artist
    colors = ("#2457A7", "#D3831F")
    labels = ("State A: 2.45 GHz", "State B: 5.8 GHz")

    output_directory.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8.0, 5.2), constrained_layout=True)
    for geometry, color, label in zip(endpoint_geometries, colors, labels, strict=True):
        path = _geometry_path(geometry.vertices, geometry.faces)
        x = [1000.0 * geometry.vertices[index][0] for index in path]
        y = [1000.0 * geometry.vertices[index][1] for index in path]
        axis.plot(x, y, color=color, linewidth=2.4, marker="o", markersize=3.2, label=label)
    axis.axhline(0.0, color="#777777", linewidth=0.8, linestyle="--")
    axis.axvline(0.0, color="#777777", linewidth=0.8, linestyle="--")
    axis.set_xlim(-21.0, 21.0)
    axis.set_ylim(-10.0, 10.0)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("x (mm)")
    axis.set_ylabel("y (mm)")
    axis.set_title("Frozen paired-state meander geometry")
    axis.legend(frameon=False, loc="upper right")
    axis.grid(color="#DDDDDD", linewidth=0.6)
    figure.savefig(output_directory / GEOMETRY_PNG_PATH.name, dpi=180)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(7.2, 5.2), constrained_layout=True)
    (line,) = axis.plot([], [], color=colors[0], linewidth=2.6, marker="o", markersize=3.0)
    caption = axis.text(0.02, 0.97, "", transform=axis.transAxes, va="top")
    axis.axhline(0.0, color="#777777", linewidth=0.8, linestyle="--")
    axis.axvline(0.0, color="#777777", linewidth=0.8, linestyle="--")
    axis.set_xlim(-21.0, 21.0)
    axis.set_ylim(-10.0, 10.0)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("x (mm)")
    axis.set_ylabel("y (mm)")
    axis.set_title("21-point archived-parameter trajectory (display only)")
    axis.grid(color="#DDDDDD", linewidth=0.6)

    def update(frame: int) -> tuple[Artist, ...]:
        geometry = geometries[frame]
        path = _geometry_path(geometry.vertices, geometry.faces)
        x = [1000.0 * geometry.vertices[index][0] for index in path]
        y = [1000.0 * geometry.vertices[index][1] for index in path]
        line.set_data(x, y)
        fraction = frame / 20.0
        line.set_color(colors[0] if fraction < 0.5 else colors[1])
        caption.set_text(f"Discrete audit point {frame + 1}/21")
        return line, caption

    from matplotlib.animation import FuncAnimation

    animation = FuncAnimation(figure, update, frames=21, interval=180, blit=False)
    animation.save(
        output_directory / TRAJECTORY_GIF_PATH.name,
        writer=PillowWriter(fps=5),
        dpi=120,
    )
    plt.close(figure)


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def write_submission_package(repo_root: Path) -> SemifinalSubmissionSummary:
    """Write deterministic report sources and display assets without solver calls."""

    root = repo_root.resolve()
    summary, document = build_submission_summary(root)
    datasets = build_submission_datasets(root, summary, document)
    output = root / SUBMISSION_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    (root / SUMMARY_PATH).write_bytes(_json_bytes(summary.model_dump(mode="json")))
    (root / ARTIFACT_PATH).write_bytes(
        _json_bytes(build_portable_artifact(summary, datasets))
    )
    (root / REPORT_PATH).write_bytes(render_report_markdown(summary))
    (root / CANDIDATE_CARD_PATH).write_bytes(render_candidate_card(summary))
    (root / EVIDENCE_INDEX_PATH).write_bytes(render_evidence_index(summary))
    write_geometry_assets(root, document, output)
    return summary


def verify_submission_package(repo_root: Path) -> SemifinalSubmissionSummary:
    """Recompute text/JSON artifacts and verify archive without writing or solving."""

    root = repo_root.resolve()
    summary, document = build_submission_summary(root)
    datasets = build_submission_datasets(root, summary, document)
    expected = {
        SUMMARY_PATH: _json_bytes(summary.model_dump(mode="json")),
        ARTIFACT_PATH: _json_bytes(build_portable_artifact(summary, datasets)),
        REPORT_PATH: render_report_markdown(summary),
        CANDIDATE_CARD_PATH: render_candidate_card(summary),
        EVIDENCE_INDEX_PATH: render_evidence_index(summary),
    }
    for relative, payload in expected.items():
        path = root / relative
        try:
            actual = path.read_bytes()
        except OSError as error:
            raise SemifinalSubmissionError(f"missing submission artifact {relative}: {error}") from error
        if actual != payload:
            raise SemifinalSubmissionError(f"submission artifact drifted: {relative}")
    if not (root / GEOMETRY_PNG_PATH).is_file() or not (root / TRAJECTORY_GIF_PATH).is_file():
        raise SemifinalSubmissionError("deterministic geometry display assets are missing")
    return summary
