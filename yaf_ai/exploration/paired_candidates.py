"""Deterministically freeze semifinal NEC2 candidates from committed archives."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_baseline import (
    ManualSingleStateEvaluationRecord,
    ManualSingleStateRejectionRecord,
    ManualWarmParentDocument,
    iter_manual_single_state_work,
)
from yaf_ai.exploration.paired_batch import (
    BATCH_PREREGISTRATION_COMMIT,
    BUDGET_SOURCE_CONFIG_HASH,
    BUDGET_SOURCE_SUMMARY_SHA256,
    FROZEN_AGENT_CELLS,
    FROZEN_EVALUATION_BUDGET,
    MANUAL_BASELINE_COMMIT,
    WARM_PARENT_DOCUMENT_SHA256,
    WARM_PARENT_HARDWARE_GRID_INDEX,
    WARM_PARENT_HARDWARE_HASH,
    WARM_PARENT_PAIR_GRID_INDEX,
    WARM_PARENT_PAIR_HASH,
    WARM_PARENT_RUN_ID,
    WARM_PARENT_SEARCH_SCORE,
    WARM_PARENT_SOURCE_STEP,
    WARM_PARENT_STATE_A_HASH,
    WARM_PARENT_STATE_B_HASH,
)
from yaf_ai.exploration.paired_meander import (
    PairedMetrics,
    PairedProposal,
    TrajectoryAudit,
    audit_trajectory,
    build_state_geometry,
    hardware_hash,
    pair_hash,
    score_paired_curves,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRejectionRecord,
    PairedRunConfig,
    PairedRunSummary,
)

CandidateCategory = Literal["top-es", "top-random", "manual-baseline"]

SOURCE_EVIDENCE_COMMIT = "a19684b5449774db82b21907cc11c7874287f838"
SELECTION_PREREGISTRATION_COMMIT = BATCH_PREREGISTRATION_COMMIT
BATCH_EXECUTION_COMMIT = "ae4022c2108763689d1f8022f2ed619125b5298f"
SOURCE_MANIFEST_SHA256 = "6de538d4ec44931eda14cd4ce1828b2962176c8af500106f48bb0fbba331ffcb"
SOURCE_MANIFEST_ENTRY_COUNT = 218
RANDOM_RUN_IDS = tuple(f"semifinal-paired-random-s{seed}" for seed in (101, 202, 303))
ES_RUN_IDS = tuple(
    f"semifinal-paired-{arm}-s{seed}" for arm in ("es-cold", "es-warm") for seed in (101, 202, 303)
)
MANUAL_RUN_IDS = ("semifinal-paired-manual-baseline",)
ALL_AGENT_RUN_IDS = RANDOM_RUN_IDS + ES_RUN_IDS
ALL_SOURCE_RUN_IDS = ALL_AGENT_RUN_IDS + MANUAL_RUN_IDS
MANUAL_PARENT_PATH = Path("artifacts/analysis/semifinal-paired-manual-baseline/warm_parent.json")
FROZEN_OUTPUT_PATH = Path("artifacts/analysis/semifinal-paired-agent-batch/frozen_candidates.json")
FROZEN_REPORT_PATH = Path("artifacts/analysis/semifinal-paired-agent-batch/report.md")


class CandidateFreezeError(RuntimeError):
    """Raised when committed source evidence or deterministic selection drifts."""


class SourceManifestEntry(BaseModel):
    """Manifest fields that bind one source run to its archived bytes."""

    model_config = ConfigDict(frozen=True, extra="allow")

    run_id: str
    role: str
    note: str
    config_hash: str
    seed: int
    steps_completed: int = Field(ge=0)
    solver_mode_counts: dict[str, int]
    sha256: dict[str, str]

    @model_validator(mode="after")
    def validate_digests(self) -> Self:
        """Require the two immutable evidence-file digests."""

        if set(self.sha256) != {"log.jsonl", "summary.json"}:
            raise ValueError("source manifest entry has an unexpected file set")
        if any(
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.sha256.values()
        ):
            raise ValueError("source manifest entry has an invalid SHA-256")
        return self


class ManualSourceSummary(BaseModel):
    """Archived manual summary fields required by the freeze."""

    model_config = ConfigDict(frozen=True, extra="allow")

    run_id: str
    config_hash: str
    seed: int
    steps_completed: int = Field(ge=0)
    solver_mode_counts: dict[str, int]
    result_status: str
    valid_pair_count: int = Field(ge=0)
    single_state_total: int = Field(ge=0)
    single_state_rejected: int = Field(ge=0)
    nec2_successes: int = Field(ge=0)
    scored_pairs: int = Field(ge=0)


class FrozenRunStatistics(BaseModel):
    """One completed agent cell summarized from committed accepted rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    agent: Literal["random", "es-cold", "es-warm"]
    seed: int
    accepted_pair_count: int = Field(gt=0)
    subprocess_curve_count: int = Field(gt=0)
    valid_pair_count: int = Field(ge=0)
    valid_pair_fraction: float = Field(ge=0.0, le=1.0)
    best_raw_base_score: float
    best_valid_base_score: float | None
    rejected_proposals: int = Field(ge=0)
    proposal_attempts: int = Field(gt=0)
    wall_seconds: float = Field(ge=0.0)


class FrozenEffectAssessment(BaseModel):
    """The preregistered NEC2 reflected-power gate against manual reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: Literal["worst-state-reflected-power-fraction"] = "worst-state-reflected-power-fraction"
    candidate_category: Literal["top-es"] = "top-es"
    reference_category: Literal["manual-baseline"] = "manual-baseline"
    candidate_value: float = Field(gt=0.0)
    reference_value: float = Field(gt=0.0)
    maximum_candidate_to_reference_ratio: float = 0.9
    observed_candidate_to_reference_ratio: float = Field(gt=0.0)
    relative_reduction_fraction: float
    threshold_fraction: float = 0.1
    passed: bool


class FrozenValidityGateDiagnostic(BaseModel):
    """Highest raw ES score excluded by the validity-first candidate rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_run_id: str
    source_step_index: int = Field(ge=0)
    pair_hash: str
    base_score: float
    worst_reflected_power_fraction: float = Field(gt=0.0)
    apparent_reduction_fraction: float
    state_a_selected_index: int = Field(ge=0)
    state_b_selected_index: int = Field(ge=0)
    valid_pair_search: bool


class FrozenCategoryCandidate(BaseModel):
    """One source-addressed NEC2-only candidate for a frozen comparison category."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: CandidateCategory
    source_run_ids: tuple[str, ...]
    source_record_count: int = Field(gt=0)
    valid_record_count: int = Field(ge=0)
    source_run_id: str
    source_step_index: int = Field(ge=0)
    source_proposal_index: int = Field(ge=0)
    source_log_sha256: str
    source_summary_sha256: str
    proposer: str
    hardware_hash: str
    state_a_geometry_hash: str
    state_b_geometry_hash: str
    pair_hash: str
    base_score: float
    search_score: float
    valid_pair_search: bool
    positive_eligible: bool
    proposal: PairedProposal
    metrics: PairedMetrics
    trajectory: TrajectoryAudit


class CandidateFreezeDocument(BaseModel):
    """Machine-verifiable three-category freeze before any openEMS output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    source_evidence_commit: str = SOURCE_EVIDENCE_COMMIT
    source_manifest_sha256: str = SOURCE_MANIFEST_SHA256
    selection_preregistration_commit: str = SELECTION_PREREGISTRATION_COMMIT
    selection_order: str = "valid_pair_search first; base_score desc; hardware_hash; run_id; step"
    matrix_budget_complete: bool = True
    openems_cross_check_authorized: Literal[False] = False
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    concept_label: Literal["paired-state-hypothesis"] = "paired-state-hypothesis"
    agent_run_statistics: tuple[FrozenRunStatistics, ...]
    effect_assessment: FrozenEffectAssessment
    validity_gate_diagnostic: FrozenValidityGateDiagnostic
    candidates: tuple[FrozenCategoryCandidate, ...]

    @model_validator(mode="after")
    def validate_categories(self) -> Self:
        """Require exactly the preregistered top-ES, top-Random, manual order."""

        if tuple(candidate.category for candidate in self.candidates) != (
            "top-es",
            "top-random",
            "manual-baseline",
        ):
            raise ValueError("candidate categories or order changed")
        if tuple(statistic.run_id for statistic in self.agent_run_statistics) != (
            ALL_AGENT_RUN_IDS
        ):
            raise ValueError("agent-run statistics or order changed")
        return self


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _config_sha256(config: PairedRunConfig) -> str:
    payload = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return _sha256(payload)


def _git(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ("git", *arguments),
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise CandidateFreezeError(f"cannot execute git evidence gate: {error}") from error


def _require_ancestor(repo_root: Path, ancestor: str, descendant: str) -> None:
    process = _git(repo_root, "merge-base", "--is-ancestor", ancestor, descendant)
    if process.returncode != 0:
        raise CandidateFreezeError(
            f"source evidence commit {ancestor} is not an ancestor of {descendant}"
        )


def _committed_bytes(repo_root: Path, path: Path) -> bytes:
    process = _git(repo_root, "show", f"{SOURCE_EVIDENCE_COMMIT}:{path.as_posix()}")
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise CandidateFreezeError(f"cannot read committed {path.as_posix()}: {stderr}")
    return process.stdout


def _require_committed_file(repo_root: Path, path: Path) -> bytes:
    try:
        current = (repo_root / path).read_bytes()
    except OSError as error:
        raise CandidateFreezeError(f"cannot read source {path}: {error}") from error
    committed = _committed_bytes(repo_root, path)
    if current != committed:
        raise CandidateFreezeError(f"source {path} differs from evidence commit")
    return current


def _manifest_entries(
    payload: bytes,
) -> tuple[tuple[dict[str, object], ...], tuple[SourceManifestEntry, ...]]:
    try:
        decoded: object = json.loads(payload)
        if not isinstance(decoded, list):
            raise CandidateFreezeError("manifest root must be an array")
        if any(not isinstance(item, dict) for item in decoded):
            raise CandidateFreezeError("manifest entries must be objects")
        raw_entries = tuple(cast(dict[str, object], item) for item in decoded)
        entries = tuple(SourceManifestEntry.model_validate(item) for item in raw_entries)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise CandidateFreezeError(f"cannot parse manifest: {error}") from error
    run_ids = tuple(entry.run_id for entry in entries)
    if len(run_ids) != len(set(run_ids)):
        raise CandidateFreezeError("manifest contains duplicate run IDs")
    return raw_entries, entries


def _manifest_index(payload: bytes) -> dict[str, SourceManifestEntry]:
    _, entries = _manifest_entries(payload)
    return {entry.run_id: entry for entry in entries}


def _canonical_manifest_entry(entry: dict[str, object]) -> bytes:
    return json.dumps(
        entry,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _validate_manifest_extension(
    pinned_payload: bytes,
    current_payload: bytes,
) -> dict[str, SourceManifestEntry]:
    pinned_raw, pinned_entries = _manifest_entries(pinned_payload)
    current_raw, current_entries = _manifest_entries(current_payload)
    if len(pinned_entries) != SOURCE_MANIFEST_ENTRY_COUNT:
        raise CandidateFreezeError(
            f"pinned manifest must contain exactly {SOURCE_MANIFEST_ENTRY_COUNT} entries"
        )
    pinned_run_ids = {entry.run_id for entry in pinned_entries}
    current_run_ids = {entry.run_id for entry in current_entries}
    missing = sorted(pinned_run_ids - current_run_ids)
    if missing:
        raise CandidateFreezeError(f"current manifest is missing pinned runs: {missing}")
    pinned_prefix = tuple(_canonical_manifest_entry(entry) for entry in pinned_raw)
    current_prefix = tuple(
        _canonical_manifest_entry(entry)
        for entry in current_raw[:SOURCE_MANIFEST_ENTRY_COUNT]
    )
    if current_prefix != pinned_prefix:
        raise CandidateFreezeError(
            "current manifest modified or reordered pinned entries; "
            "only appended entries are allowed"
        )
    return {entry.run_id: entry for entry in current_entries}


def _validate_source_commit(
    repo_root: Path,
) -> dict[str, SourceManifestEntry]:
    process = _git(repo_root, "rev-parse", "HEAD")
    if process.returncode != 0:
        raise CandidateFreezeError("cannot resolve candidate-freeze HEAD")
    head = process.stdout.decode("ascii").strip()
    _require_ancestor(repo_root, SOURCE_EVIDENCE_COMMIT, head)
    _require_ancestor(repo_root, SELECTION_PREREGISTRATION_COMMIT, head)
    _require_ancestor(
        repo_root,
        SELECTION_PREREGISTRATION_COMMIT,
        SOURCE_EVIDENCE_COMMIT,
    )
    _require_ancestor(
        repo_root,
        BATCH_EXECUTION_COMMIT,
        SOURCE_EVIDENCE_COMMIT,
    )
    _require_ancestor(
        repo_root,
        MANUAL_BASELINE_COMMIT,
        SOURCE_EVIDENCE_COMMIT,
    )
    manifest_path = Path("artifacts/runs/manifest.json")
    pinned_manifest = _committed_bytes(repo_root, manifest_path)
    if _sha256(pinned_manifest) != SOURCE_MANIFEST_SHA256:
        raise CandidateFreezeError("source manifest SHA-256 changed")
    try:
        current_manifest = (repo_root / manifest_path).read_bytes()
    except OSError as error:
        raise CandidateFreezeError(f"cannot read source {manifest_path}: {error}") from error
    index = _validate_manifest_extension(pinned_manifest, current_manifest)
    missing = sorted(set(ALL_SOURCE_RUN_IDS) - set(index))
    if missing:
        raise CandidateFreezeError(f"source manifest is missing runs: {missing}")
    return index


def _load_paired_evaluations_bytes(
    payload: bytes,
    *,
    run_id: str,
    allow_manual_events: bool,
) -> tuple[
    tuple[PairedEvaluationRecord, ...],
    int,
    tuple[int, ...],
    int,
    int,
    tuple[str, ...],
]:
    """Parse every event directly from the pinned Git blob bytes."""

    records: list[PairedEvaluationRecord] = []
    rejected = 0
    proposal_indexes: list[int] = []
    single_state_evaluations = 0
    single_state_rejections = 0
    manual_event_sequence: list[str] = []
    try:
        for line in payload.decode("utf-8").splitlines():
            item = json.loads(line)
            event_type = item.get("event_type")
            if event_type == "paired_evaluation":
                record = PairedEvaluationRecord.model_validate(item)
                records.append(record)
                proposal_indexes.append(record.proposal_index)
            elif event_type == "paired_rejection":
                rejection = PairedRejectionRecord.model_validate(item)
                if rejection.run_id != run_id:
                    raise CandidateFreezeError(f"source rejection run ID drifted for {run_id}")
                rejected += 1
                proposal_indexes.append(rejection.proposal_index)
            elif event_type == "single_state_evaluation" and allow_manual_events:
                single = ManualSingleStateEvaluationRecord.model_validate(item)
                if single.run_id != run_id:
                    raise CandidateFreezeError(f"manual evaluation run ID drifted for {run_id}")
                single_state_evaluations += 1
                manual_event_sequence.append(
                    _manual_event_identity(
                        single.hardware_grid_index,
                        single.state_grid_index,
                        single.key.model_dump(mode="json"),
                    )
                )
            elif event_type == "single_state_rejected" and allow_manual_events:
                single_rejection = ManualSingleStateRejectionRecord.model_validate(item)
                if single_rejection.run_id != run_id:
                    raise CandidateFreezeError(f"manual rejection run ID drifted for {run_id}")
                single_state_rejections += 1
                manual_event_sequence.append(
                    _manual_event_identity(
                        single_rejection.hardware_grid_index,
                        single_rejection.state_grid_index,
                        single_rejection.key.model_dump(mode="json"),
                    )
                )
            else:
                raise CandidateFreezeError(
                    f"unknown committed event type in {run_id}: {event_type!r}"
                )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, CandidateFreezeError):
            raise
        raise CandidateFreezeError(f"cannot parse committed log {run_id}: {error}") from error
    if any(record.run_id != run_id for record in records):
        raise CandidateFreezeError(f"source record run ID drifted for {run_id}")
    steps = tuple(record.step_index for record in records)
    if steps != tuple(range(len(records))):
        raise CandidateFreezeError(f"accepted step sequence drifted for {run_id}")
    return (
        tuple(records),
        rejected,
        tuple(proposal_indexes),
        single_state_evaluations,
        single_state_rejections,
        tuple(manual_event_sequence),
    )


def _manual_event_identity(
    hardware_grid_index: int,
    state_grid_index: int,
    key: dict[str, object],
) -> str:
    return json.dumps(
        {
            "hardware_grid_index": hardware_grid_index,
            "state_grid_index": state_grid_index,
            "key": key,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _expected_manual_event_sequence() -> tuple[str, ...]:
    return tuple(
        _manual_event_identity(
            work.hardware_grid_index,
            work.state_grid_index,
            work.key.model_dump(mode="json"),
        )
        for work in iter_manual_single_state_work()
    )


def _validate_record_search_semantics(record: PairedEvaluationRecord) -> None:
    evaluation = record.evaluation
    if hardware_hash(record.proposal.hardware) != evaluation.hardware_hash:
        raise CandidateFreezeError(
            f"hardware hash does not reconstruct at {record.run_id}:{record.step_index}"
        )
    if (
        score_paired_curves(
            evaluation.state_a_curve,
            evaluation.state_b_curve,
        )
        != evaluation.metrics
    ):
        raise CandidateFreezeError(
            f"search metrics do not recompute at {record.run_id}:{record.step_index}"
        )
    for curve in (evaluation.state_a_curve, evaluation.state_b_curve):
        if (
            curve.solver_name != "nec2"
            or curve.solver_mode != "subprocess"
            or curve.realized_gain_dbi is not None
        ):
            raise CandidateFreezeError(
                f"source curve escaped subprocess-only NEC2 search at "
                f"{record.run_id}:{record.step_index}"
            )


def _validate_selected_semantics(record: PairedEvaluationRecord) -> None:
    evaluation = record.evaluation
    proposal = record.proposal
    geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
    geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
    expected = (
        state_geometry_hash(proposal.hardware, proposal.state_a, geometry_a),
        state_geometry_hash(proposal.hardware, proposal.state_b, geometry_b),
        pair_hash(proposal),
        audit_trajectory(proposal),
    )
    actual = (
        evaluation.state_a_geometry_hash,
        evaluation.state_b_geometry_hash,
        evaluation.pair_hash,
        evaluation.trajectory,
    )
    if actual != expected:
        raise CandidateFreezeError(
            f"selected geometry or trajectory does not reconstruct at "
            f"{record.run_id}:{record.step_index}"
        )


def _load_category_records(
    repo_root: Path,
    run_ids: Sequence[str],
    *,
    require_full_agent_run: bool,
    manifest: dict[str, SourceManifestEntry],
) -> tuple[
    tuple[PairedEvaluationRecord, ...],
    dict[str, tuple[str, str]],
    dict[str, PairedRunSummary],
]:
    records: list[PairedEvaluationRecord] = []
    source_hashes: dict[str, tuple[str, str]] = {}
    summaries: dict[str, PairedRunSummary] = {}
    for run_id in run_ids:
        directory = Path("artifacts/runs") / run_id
        log_path = directory / "log.jsonl"
        summary_path = directory / "summary.json"
        log_bytes = _require_committed_file(repo_root, log_path)
        summary_bytes = _require_committed_file(repo_root, summary_path)
        log_digest = _sha256(log_bytes)
        summary_digest = _sha256(summary_bytes)
        source_hashes[run_id] = (log_digest, summary_digest)
        entry = manifest[run_id]
        if entry.sha256 != {
            "log.jsonl": log_digest,
            "summary.json": summary_digest,
        }:
            raise CandidateFreezeError(f"manifest digest binding failed for {run_id}")
        (
            loaded,
            rejected_events,
            proposal_indexes,
            single_state_evaluations,
            single_state_rejections,
            manual_event_sequence,
        ) = _load_paired_evaluations_bytes(
            log_bytes,
            run_id=run_id,
            allow_manual_events=not require_full_agent_run,
        )
        for record in loaded:
            _validate_record_search_semantics(record)
        if require_full_agent_run:
            try:
                summary = PairedRunSummary.model_validate_json(summary_bytes)
            except ValueError as error:
                raise CandidateFreezeError(
                    f"cannot validate agent summary {run_id}: {error}"
                ) from error
            expected_cell = next(
                (cell for cell in FROZEN_AGENT_CELLS if cell.run_id == run_id),
                None,
            )
            if expected_cell is None:
                raise CandidateFreezeError(f"run {run_id} is not a frozen matrix cell")
            try:
                config = PairedRunConfig.model_validate(summary.config)
            except ValueError as error:
                raise CandidateFreezeError(
                    f"cannot validate agent config {run_id}: {error}"
                ) from error
            expected_role = "baseline-random" if expected_cell.agent == "random" else "other"
            expected_note = (
                f"batch=semifinal-paired agent={expected_cell.agent} seed={expected_cell.seed}"
            )
            if (
                summary.run_id != run_id
                or summary.seed != expected_cell.seed
                or summary.status != "completed"
                or summary.steps_completed != 300
                or summary.evaluation_budget != FROZEN_EVALUATION_BUDGET
                or summary.solver_mode_counts != {"subprocess": 600}
                or len(loaded) != 300
                or rejected_events != summary.rejected_proposals
                or single_state_evaluations != 0
                or single_state_rejections != 0
                or manual_event_sequence
                or len(proposal_indexes) != summary.proposal_attempts
                or proposal_indexes != tuple(range(summary.proposal_attempts))
                or config.run_id != run_id
                or config.agent != expected_cell.agent
                or config.seed != expected_cell.seed
                or config.evaluation_budget != FROZEN_EVALUATION_BUDGET
                or config.anchor_released
                or config.openems_cross_check_authorized
                or config.preregistration_commit != BATCH_PREREGISTRATION_COMMIT
                or config.execution_commit != BATCH_EXECUTION_COMMIT
                or summary.config_hash != _config_sha256(config)
                or config.budget_source_summary_sha256 != BUDGET_SOURCE_SUMMARY_SHA256
                or config.budget_source_config_hash != BUDGET_SOURCE_CONFIG_HASH
                or entry.role != expected_role
                or entry.note != expected_note
            ):
                raise CandidateFreezeError(f"agent run {run_id} is not a complete frozen cell")
            if expected_cell.agent == "es-warm":
                warm_values = (
                    config.manual_baseline_commit == MANUAL_BASELINE_COMMIT,
                    config.warm_parent_run_id == WARM_PARENT_RUN_ID,
                    config.warm_parent_pair_hash == WARM_PARENT_PAIR_HASH,
                    config.warm_parent_document_sha256 == WARM_PARENT_DOCUMENT_SHA256,
                    config.warm_parent_hardware_hash == WARM_PARENT_HARDWARE_HASH,
                    config.warm_parent_state_a_geometry_hash == WARM_PARENT_STATE_A_HASH,
                    config.warm_parent_state_b_geometry_hash == WARM_PARENT_STATE_B_HASH,
                    config.warm_parent_step_index == WARM_PARENT_SOURCE_STEP,
                    config.warm_parent_hardware_grid_index == WARM_PARENT_HARDWARE_GRID_INDEX,
                    config.warm_parent_pair_grid_index == WARM_PARENT_PAIR_GRID_INDEX,
                    config.warm_parent_search_score == WARM_PARENT_SEARCH_SCORE,
                )
                if not all(warm_values):
                    raise CandidateFreezeError(f"warm provenance drifted for {run_id}")
            expected_proposer = "random" if expected_cell.agent == "random" else "es"
            if any(record.proposer != expected_proposer for record in loaded):
                raise CandidateFreezeError(f"proposer label drifted for {run_id}")
            summaries[run_id] = summary
            source_summary: PairedRunSummary | ManualSourceSummary = summary
        else:
            try:
                manual_summary = ManualSourceSummary.model_validate_json(summary_bytes)
            except ValueError as error:
                raise CandidateFreezeError(
                    f"cannot validate manual summary {run_id}: {error}"
                ) from error
            if (
                manual_summary.run_id != run_id
                or manual_summary.result_status != "completed"
                or manual_summary.valid_pair_count != 0
                or len(loaded) != manual_summary.scored_pairs
                or rejected_events != 0
                or manual_summary.single_state_total != len(manual_event_sequence)
                or manual_summary.nec2_successes != single_state_evaluations
                or manual_summary.single_state_rejected != single_state_rejections
                or manual_summary.steps_completed != single_state_evaluations
                or manual_summary.solver_mode_counts != {"subprocess": single_state_evaluations}
                or manual_event_sequence != _expected_manual_event_sequence()
                or len(set(proposal_indexes)) != len(proposal_indexes)
                or entry.role != "other"
                or entry.note
                != (
                    "baseline=manual-reconfigurable; frozen v3.4 section 8 "
                    "discrete template; warm parent diagnostic only"
                )
                or any(record.proposer != "manual-physics-baseline" for record in loaded)
            ):
                raise CandidateFreezeError(f"manual source identity drifted for {run_id}")
            source_summary = manual_summary
        if (
            entry.config_hash != source_summary.config_hash
            or entry.seed != source_summary.seed
            or entry.steps_completed != source_summary.steps_completed
            or entry.solver_mode_counts != source_summary.solver_mode_counts
        ):
            raise CandidateFreezeError(f"manifest metadata binding failed for {run_id}")
        records.extend(loaded)
    return tuple(records), source_hashes, summaries


def _select_category(
    category: CandidateCategory,
    run_ids: tuple[str, ...],
    records: Sequence[PairedEvaluationRecord],
    source_hashes: dict[str, tuple[str, str]],
) -> FrozenCategoryCandidate:
    if not records:
        raise CandidateFreezeError(f"candidate pool {category} is empty")
    valid = [record for record in records if record.evaluation.metrics.valid_pair_search]
    positive_eligible = bool(valid)
    pool = valid if valid else list(records)
    selected = min(
        pool,
        key=lambda record: (
            -record.evaluation.metrics.base_score,
            record.evaluation.hardware_hash,
            record.run_id,
            record.step_index,
        ),
    )
    _validate_selected_semantics(selected)
    evaluation = selected.evaluation
    log_sha256, summary_sha256 = source_hashes[selected.run_id]
    return FrozenCategoryCandidate(
        category=category,
        source_run_ids=run_ids,
        source_record_count=len(records),
        valid_record_count=len(valid),
        source_run_id=selected.run_id,
        source_step_index=selected.step_index,
        source_proposal_index=selected.proposal_index,
        source_log_sha256=log_sha256,
        source_summary_sha256=summary_sha256,
        proposer=selected.proposer,
        hardware_hash=evaluation.hardware_hash,
        state_a_geometry_hash=evaluation.state_a_geometry_hash,
        state_b_geometry_hash=evaluation.state_b_geometry_hash,
        pair_hash=evaluation.pair_hash,
        base_score=evaluation.metrics.base_score,
        search_score=evaluation.metrics.search_score,
        valid_pair_search=evaluation.metrics.valid_pair_search,
        positive_eligible=positive_eligible,
        proposal=selected.proposal,
        metrics=evaluation.metrics,
        trajectory=evaluation.trajectory,
    )


def _select_manual_category(
    repo_root: Path,
    records: Sequence[PairedEvaluationRecord],
    source_hashes: dict[str, tuple[str, str]],
) -> FrozenCategoryCandidate:
    parent_bytes = _require_committed_file(repo_root, MANUAL_PARENT_PATH)
    if _sha256(parent_bytes) != WARM_PARENT_DOCUMENT_SHA256:
        raise CandidateFreezeError("manual warm-parent document SHA-256 changed")
    try:
        parent = ManualWarmParentDocument.model_validate_json(parent_bytes)
    except ValueError as error:
        raise CandidateFreezeError(f"cannot validate manual warm parent: {error}") from error
    selected = [
        record
        for record in records
        if record.run_id == parent.parent_run_id
        and record.step_index == WARM_PARENT_SOURCE_STEP
        and record.evaluation.pair_hash == parent.pair_hash
    ]
    if len(selected) != 1:
        raise CandidateFreezeError("frozen manual parent source row is not unique")
    record = selected[0]
    evaluation = record.evaluation
    parent_fields_match = (
        parent.parent_run_id == WARM_PARENT_RUN_ID,
        parent.pair_hash == WARM_PARENT_PAIR_HASH,
        parent.hardware_hash == WARM_PARENT_HARDWARE_HASH,
        parent.state_a_geometry_hash == WARM_PARENT_STATE_A_HASH,
        parent.state_b_geometry_hash == WARM_PARENT_STATE_B_HASH,
        parent.hardware_grid_index == WARM_PARENT_HARDWARE_GRID_INDEX,
        parent.pair_grid_index == WARM_PARENT_PAIR_GRID_INDEX,
        parent.search_score == WARM_PARENT_SEARCH_SCORE,
        record.hardware_grid_index == parent.hardware_grid_index,
        record.pair_grid_index == parent.pair_grid_index,
        parent.proposal == record.proposal,
        parent.base_score == evaluation.metrics.base_score,
        not parent.valid_pair_search,
        not parent.positive_eligible,
    )
    if not all(parent_fields_match):
        raise CandidateFreezeError("manual parent fields differ from the committed source row")
    _validate_selected_semantics(record)
    log_sha256, summary_sha256 = source_hashes[record.run_id]
    return FrozenCategoryCandidate(
        category="manual-baseline",
        source_run_ids=MANUAL_RUN_IDS,
        source_record_count=len(records),
        valid_record_count=sum(1 for item in records if item.evaluation.metrics.valid_pair_search),
        source_run_id=record.run_id,
        source_step_index=record.step_index,
        source_proposal_index=record.proposal_index,
        source_log_sha256=log_sha256,
        source_summary_sha256=summary_sha256,
        proposer=record.proposer,
        hardware_hash=evaluation.hardware_hash,
        state_a_geometry_hash=evaluation.state_a_geometry_hash,
        state_b_geometry_hash=evaluation.state_b_geometry_hash,
        pair_hash=evaluation.pair_hash,
        base_score=evaluation.metrics.base_score,
        search_score=evaluation.metrics.search_score,
        valid_pair_search=evaluation.metrics.valid_pair_search,
        positive_eligible=False,
        proposal=record.proposal,
        metrics=evaluation.metrics,
        trajectory=evaluation.trajectory,
    )


def _run_statistics(
    records: Sequence[PairedEvaluationRecord],
    summaries: dict[str, PairedRunSummary],
) -> tuple[FrozenRunStatistics, ...]:
    output: list[FrozenRunStatistics] = []
    for cell in FROZEN_AGENT_CELLS:
        cell_records = tuple(record for record in records if record.run_id == cell.run_id)
        valid = tuple(
            record for record in cell_records if record.evaluation.metrics.valid_pair_search
        )
        summary = summaries[cell.run_id]
        output.append(
            FrozenRunStatistics(
                run_id=cell.run_id,
                agent=cell.agent,
                seed=cell.seed,
                accepted_pair_count=len(cell_records),
                subprocess_curve_count=summary.solver_mode_counts["subprocess"],
                valid_pair_count=len(valid),
                valid_pair_fraction=len(valid) / len(cell_records),
                best_raw_base_score=max(
                    record.evaluation.metrics.base_score for record in cell_records
                ),
                best_valid_base_score=(
                    max(record.evaluation.metrics.base_score for record in valid) if valid else None
                ),
                rejected_proposals=summary.rejected_proposals,
                proposal_attempts=summary.proposal_attempts,
                wall_seconds=(summary.finished_at - summary.started_at).total_seconds(),
            )
        )
    return tuple(output)


def _effect_assessment(
    top_es: FrozenCategoryCandidate,
    manual: FrozenCategoryCandidate,
) -> FrozenEffectAssessment:
    candidate_value = top_es.metrics.worst_reflected_power_fraction
    reference_value = manual.metrics.worst_reflected_power_fraction
    ratio = candidate_value / reference_value
    return FrozenEffectAssessment(
        candidate_value=candidate_value,
        reference_value=reference_value,
        observed_candidate_to_reference_ratio=ratio,
        relative_reduction_fraction=1.0 - ratio,
        passed=ratio <= 0.9,
    )


def _validity_gate_diagnostic(
    es_records: Sequence[PairedEvaluationRecord],
    manual: FrozenCategoryCandidate,
) -> FrozenValidityGateDiagnostic:
    record = min(
        es_records,
        key=lambda item: (
            -item.evaluation.metrics.base_score,
            item.evaluation.hardware_hash,
            item.run_id,
            item.step_index,
        ),
    )
    metrics = record.evaluation.metrics
    return FrozenValidityGateDiagnostic(
        source_run_id=record.run_id,
        source_step_index=record.step_index,
        pair_hash=record.evaluation.pair_hash,
        base_score=metrics.base_score,
        worst_reflected_power_fraction=(metrics.worst_reflected_power_fraction),
        apparent_reduction_fraction=(
            1.0
            - metrics.worst_reflected_power_fraction / manual.metrics.worst_reflected_power_fraction
        ),
        state_a_selected_index=metrics.state_a.selected_index,
        state_b_selected_index=metrics.state_b.selected_index,
        valid_pair_search=metrics.valid_pair_search,
    )


def build_candidate_freeze(repo_root: Path) -> CandidateFreezeDocument:
    """Recompute all three selections strictly from committed artifact logs."""

    root = repo_root.resolve()
    manifest = _validate_source_commit(root)
    es_records, es_hashes, es_summaries = _load_category_records(
        root,
        ES_RUN_IDS,
        require_full_agent_run=True,
        manifest=manifest,
    )
    random_records, random_hashes, random_summaries = _load_category_records(
        root,
        RANDOM_RUN_IDS,
        require_full_agent_run=True,
        manifest=manifest,
    )
    manual_records, manual_hashes, _ = _load_category_records(
        root,
        MANUAL_RUN_IDS,
        require_full_agent_run=False,
        manifest=manifest,
    )
    top_es = _select_category(
        "top-es",
        ES_RUN_IDS,
        es_records,
        es_hashes,
    )
    top_random = _select_category(
        "top-random",
        RANDOM_RUN_IDS,
        random_records,
        random_hashes,
    )
    manual = _select_manual_category(
        root,
        manual_records,
        manual_hashes,
    )
    return CandidateFreezeDocument(
        agent_run_statistics=_run_statistics(
            random_records + es_records,
            random_summaries | es_summaries,
        ),
        effect_assessment=_effect_assessment(top_es, manual),
        validity_gate_diagnostic=_validity_gate_diagnostic(
            es_records,
            manual,
        ),
        candidates=(top_es, top_random, manual),
    )


def _document_bytes(document: CandidateFreezeDocument) -> bytes:
    return (
        json.dumps(
            document.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def write_once_or_match(path: Path, expected: bytes) -> None:
    """Atomically publish complete bytes without overwriting an existing freeze."""

    if path.exists():
        try:
            actual = path.read_bytes()
        except OSError as error:
            raise CandidateFreezeError(f"cannot read existing freeze artifact: {error}") from error
        if actual != expected:
            raise CandidateFreezeError(
                f"refusing to overwrite changed freeze artifact: {path.name}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(expected)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            actual = path.read_bytes()
            if actual != expected:
                raise CandidateFreezeError(
                    f"refusing to overwrite changed freeze artifact: {path.name}"
                ) from None
    except CandidateFreezeError:
        raise
    except OSError as error:
        raise CandidateFreezeError(f"cannot create freeze artifact {path}: {error}") from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def write_or_verify_candidate_freeze(
    repo_root: Path,
    *,
    verify: bool,
    output_path: Path | None = None,
) -> CandidateFreezeDocument:
    """Write the deterministic artifact, or prove an existing artifact equals it."""

    root = repo_root.resolve()
    document = build_candidate_freeze(root)
    expected = _document_bytes(document)
    relative = FROZEN_OUTPUT_PATH if output_path is None else output_path
    destination = relative if relative.is_absolute() else root / relative
    if verify:
        try:
            actual = destination.read_bytes()
        except OSError as error:
            raise CandidateFreezeError(f"cannot read frozen-candidate artifact: {error}") from error
        if actual != expected:
            raise CandidateFreezeError("frozen-candidate artifact does not recompute")
        return document
    write_once_or_match(destination, expected)
    return document
