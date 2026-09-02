"""Deterministic analysis for the B-parent conditional-completion study."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_meander import (
    PairedProposal,
    audit_trajectory,
    hardware_hash,
    pair_hash,
    score_paired_curves,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_runner import PairedEvaluationRecord

STUDY_ID = "semifinal-paired-b-parent-conditional-completion-v1"
SPEC_REVISION = "1.0-b-parent-a-only-exact-support"
MAPPING_VERSION = "b-parent-a-only-exact-support-v1"
L_REQUIRED = 0.19394054289730642
EVALUATION_BUDGET = 300
SEEDS = (101, 202, 303, 404, 505)
PARENTS = ("p01", "p02")
AGENTS = ("random-b-completion", "es-b-completion")

ParentId = Literal["p01", "p02"]
Agent = Literal["random-b-completion", "es-b-completion"]
CellStatus = Literal["completed", "execution_failed", "not_run_after_matrix_abort"]
ScientificEndpoint = Literal[
    "b_completion_effect_crossing_observed",
    "b_completion_pair_validity_without_effect_crossing",
    "no_b_completion_pair_observed",
]


def _is_sha256(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def expected_run_id(parent_id: ParentId, agent: Agent, seed: int) -> str:
    """Return the sole preregistered run ID for one matrix cell."""

    slug = "random" if agent == "random-b-completion" else "es"
    return f"semifinal-paired-b-completion-{parent_id}-{slug}-s{seed}"


class BCompletionRecordRef(BaseModel):
    """One source-addressed accepted record used by the frozen hypotheses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: ParentId
    agent: Agent
    seed: int
    run_id: str
    step_index: int = Field(ge=0)
    proposal_index: int = Field(ge=0)
    proposer: str = Field(min_length=1)
    proposal: PairedProposal
    hardware_hash: str
    state_a_geometry_hash: str
    state_b_geometry_hash: str
    pair_hash: str
    valid_pair_search: bool
    base_score: float
    search_score: float
    worst_reflected_power_fraction: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.seed not in SEEDS:
            raise ValueError("B-completion record seed is not preregistered")
        if self.run_id != expected_run_id(self.parent_id, self.agent, self.seed):
            raise ValueError("B-completion record belongs to another matrix cell")
        if self.proposer != self.agent or self.proposal.proposer != self.agent:
            raise ValueError("B-completion proposer identity changed")
        hashes = (
            self.hardware_hash,
            self.state_a_geometry_hash,
            self.state_b_geometry_hash,
            self.pair_hash,
        )
        if not all(_is_sha256(value) for value in hashes):
            raise ValueError("B-completion record hashes must be lowercase SHA-256")
        return self

    @property
    def h1(self) -> bool:
        """Return the frozen pair-validity hypothesis result."""

        return self.valid_pair_search

    @property
    def h2(self) -> bool:
        """Return the frozen effect-crossing hypothesis result."""

        return self.h1 and self.worst_reflected_power_fraction <= L_REQUIRED


class BCompletionCellRow(BaseModel):
    """One of the twenty frozen parent-by-agent-by-seed matrix cells."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: ParentId
    agent: Agent
    seed: int
    run_id: str
    execution_status: CellStatus
    source_status: str | None = None
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    proposal_attempts: int = Field(ge=0)
    solver_mode_counts: dict[str, int]
    h1_count: int = Field(ge=0)
    h2_count: int = Field(ge=0)
    log_sha256: str | None = None
    summary_sha256: str | None = None
    partial_log_bytes: int | None = Field(default=None, ge=0)
    partial_log_lines: int | None = Field(default=None, ge=0)
    expected_b_hashes: dict[str, str] | None = None
    actual_b_hashes: dict[str, str] | None = None
    exception_type: str | None = None
    exception_message: str | None = None

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        if self.seed not in SEEDS or self.run_id != expected_run_id(
            self.parent_id, self.agent, self.seed
        ):
            raise ValueError("B-completion cell identity changed")
        if self.h2_count > self.h1_count or self.h1_count > self.accepted_count:
            raise ValueError("B-completion hypothesis counts are inconsistent")
        if self.accepted_count + self.rejected_count > self.proposal_attempts:
            raise ValueError("B-completion attempt counts are inconsistent")
        if any(count < 0 for count in self.solver_mode_counts.values()):
            raise ValueError("B-completion solver-mode count is negative")
        if self.execution_status == "completed":
            if (
                self.source_status != "completed"
                or self.accepted_count != EVALUATION_BUDGET
                or self.rejected_count != 0
                or self.proposal_attempts != EVALUATION_BUDGET
                or self.solver_mode_counts != {"subprocess": 2 * EVALUATION_BUDGET}
                or not _is_sha256(self.log_sha256)
                or not _is_sha256(self.summary_sha256)
                or self.partial_log_bytes is not None
                or self.partial_log_lines is not None
                or self.expected_b_hashes is not None
                or self.actual_b_hashes is not None
                or self.exception_type is not None
                or self.exception_message is not None
            ):
                raise ValueError("completed B-completion cell violates its frozen terminal")
        elif self.execution_status == "execution_failed":
            if (
                not self.exception_type
                or not self.exception_message
                or not _is_sha256(self.log_sha256)
                or self.partial_log_bytes is None
                or self.partial_log_lines is None
            ):
                raise ValueError("failed B-completion cell lacks exception evidence")
            if self.summary_sha256 is not None and not _is_sha256(self.summary_sha256):
                raise ValueError("failed B-completion summary hash is invalid")
            if (self.expected_b_hashes is None) != (self.actual_b_hashes is None):
                raise ValueError("expected and actual B hashes must be recorded together")
            for hashes in (self.expected_b_hashes, self.actual_b_hashes):
                if hashes is not None and (
                    not hashes or not all(_is_sha256(value) for value in hashes.values())
                ):
                    raise ValueError("B-hash failure evidence is invalid")
            if (
                self.expected_b_hashes is not None
                and self.actual_b_hashes is not None
                and self.expected_b_hashes.keys() != self.actual_b_hashes.keys()
            ):
                raise ValueError("expected and actual B-hash keys differ")
        elif (
            self.source_status is not None
            or self.accepted_count != 0
            or self.rejected_count != 0
            or self.proposal_attempts != 0
            or self.solver_mode_counts
            or self.h1_count != 0
            or self.h2_count != 0
            or self.log_sha256 is not None
            or self.summary_sha256 is not None
            or self.partial_log_bytes is not None
            or self.partial_log_lines is not None
            or self.expected_b_hashes is not None
            or self.actual_b_hashes is not None
            or self.exception_type is not None
            or self.exception_message is not None
        ):
            raise ValueError("not-run B-completion cell carries execution evidence")
        return self


class BCompletionSeedSupport(BaseModel):
    """Five-seed H1/H2 support counts for one parent-by-agent cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: ParentId
    agent: Agent
    h1_seeds: tuple[int, ...]
    h2_seeds: tuple[int, ...]
    h1_seed_count: int = Field(ge=0, le=5)
    h2_seed_count: int = Field(ge=0, le=5)

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if self.h1_seeds != tuple(sorted(set(self.h1_seeds))):
            raise ValueError("H1 seed support must be unique and sorted")
        if self.h2_seeds != tuple(sorted(set(self.h2_seeds))):
            raise ValueError("H2 seed support must be unique and sorted")
        if any(seed not in SEEDS for seed in self.h1_seeds + self.h2_seeds):
            raise ValueError("seed support contains an unregistered seed")
        if not set(self.h2_seeds).issubset(self.h1_seeds):
            raise ValueError("H2 seed support must be a subset of H1 support")
        if self.h1_seed_count != len(self.h1_seeds) or self.h2_seed_count != len(
            self.h2_seeds
        ):
            raise ValueError("seed support counts do not match their seed lists")
        return self


class BCompletionAppendix(BaseModel):
    """Strict appendix whose scientific aggregates are null on matrix failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study_id: str = STUDY_ID
    spec_revision: str = SPEC_REVISION
    mapping_version: str = MAPPING_VERSION
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    study_status: str = Field(min_length=1)
    rows: tuple[BCompletionCellRow, ...]
    h1_count: int | None = Field(default=None, ge=0)
    h2_count: int | None = Field(default=None, ge=0)
    seed_support: tuple[BCompletionSeedSupport, ...] | None = None
    scientific_endpoint: ScientificEndpoint | None = None
    selected_hypothesis: BCompletionRecordRef | None = None
    completed_prefix: tuple[str, ...] | None = None
    failed_run_id: str | None = None
    matrix_exception_type: str | None = None
    matrix_exception_message: str | None = None

    @model_validator(mode="after")
    def validate_aggregates(self) -> Self:
        expected = tuple(
            (parent_id, agent, seed)
            for parent_id in PARENTS
            for agent in AGENTS
            for seed in SEEDS
        )
        actual = tuple((row.parent_id, row.agent, row.seed) for row in self.rows)
        if actual != expected:
            raise ValueError("B-completion rows are not in the frozen matrix order")
        complete = all(row.execution_status == "completed" for row in self.rows)
        if (self.study_status == "complete") != complete:
            raise ValueError("B-completion study status disagrees with cell terminals")
        aggregates = (
            self.h1_count,
            self.h2_count,
            self.seed_support,
            self.scientific_endpoint,
            self.selected_hypothesis,
        )
        if not complete:
            if any(value is not None for value in aggregates):
                raise ValueError("failed B-completion study cannot carry aggregates")
            if not self.matrix_exception_type or not self.matrix_exception_message:
                raise ValueError("failed B-completion study lacks terminal evidence")
            expected_prefix: list[str] = []
            first_noncomplete: BCompletionCellRow | None = None
            for row in self.rows:
                if first_noncomplete is None and row.execution_status == "completed":
                    expected_prefix.append(row.run_id)
                elif first_noncomplete is None:
                    first_noncomplete = row
                elif row.execution_status != "not_run_after_matrix_abort":
                    raise ValueError("failed matrix rows do not form one frozen prefix")
            if self.completed_prefix != tuple(expected_prefix):
                raise ValueError("failed matrix completed-prefix evidence changed")
            if self.study_status == "support_certificate_failed":
                if (
                    self.failed_run_id is not None
                    or expected_prefix
                    or any(
                        row.execution_status != "not_run_after_matrix_abort"
                        for row in self.rows
                    )
                ):
                    raise ValueError("certificate failure cannot carry matrix execution")
            elif (
                first_noncomplete is None
                or first_noncomplete.execution_status != "execution_failed"
                or self.failed_run_id != first_noncomplete.run_id
            ):
                raise ValueError("terminal matrix failure lacks its failed run ID")
            return self
        if (
            self.matrix_exception_type is not None
            or self.matrix_exception_message is not None
            or self.completed_prefix is not None
            or self.failed_run_id is not None
        ):
            raise ValueError("complete B-completion study cannot carry an exception")
        expected_h1 = sum(row.h1_count for row in self.rows)
        expected_h2 = sum(row.h2_count for row in self.rows)
        if self.h1_count != expected_h1 or self.h2_count != expected_h2:
            raise ValueError("B-completion aggregate counts do not match the cell rows")
        expected_support = _seed_support(self.rows)
        if self.seed_support != expected_support:
            raise ValueError("B-completion seed support does not match the cell rows")
        expected_endpoint = _scientific_endpoint(expected_h1, expected_h2)
        if self.scientific_endpoint != expected_endpoint:
            raise ValueError("B-completion scientific endpoint does not recompute")
        if expected_h1 == 0:
            if self.selected_hypothesis is not None:
                raise ValueError("no-H1 endpoint cannot select a hypothesis")
        else:
            selected = self.selected_hypothesis
            if selected is None or not selected.h1:
                raise ValueError("H1 endpoint requires an H1 selected hypothesis")
            if expected_h2 > 0 and not selected.h2:
                raise ValueError("H2 endpoint must select an H2 hypothesis")
            matching_row = next(
                (
                    row
                    for row in self.rows
                    if (row.parent_id, row.agent, row.seed, row.run_id)
                    == (selected.parent_id, selected.agent, selected.seed, selected.run_id)
                ),
                None,
            )
            if matching_row is None or matching_row.h1_count == 0:
                raise ValueError("selected hypothesis has no supporting matrix cell")
        return self


def record_ref(
    record: PairedEvaluationRecord,
    parent_id: ParentId,
    agent: Agent,
    seed: int,
) -> BCompletionRecordRef:
    """Validate and reduce a generic paired record to analysis evidence."""

    if record.run_id != expected_run_id(parent_id, agent, seed):
        raise ValueError("paired record run ID differs from its B-completion cell")
    evaluation = record.evaluation
    if (
        record.proposer != agent
        or record.proposal.proposer != agent
        or evaluation.state_a_curve.solver_mode != "subprocess"
        or evaluation.state_b_curve.solver_mode != "subprocess"
    ):
        raise ValueError("B-completion accepted record violates execution semantics")
    expected_trajectory = audit_trajectory(record.proposal)
    expected_metrics = score_paired_curves(
        evaluation.state_a_curve,
        evaluation.state_b_curve,
    )
    if (
        evaluation.trajectory != expected_trajectory
        or evaluation.metrics != expected_metrics
        or evaluation.hardware_hash != hardware_hash(record.proposal.hardware)
        or evaluation.state_a_geometry_hash
        != state_geometry_hash(record.proposal.hardware, record.proposal.state_a)
        or evaluation.state_b_geometry_hash
        != state_geometry_hash(record.proposal.hardware, record.proposal.state_b)
        or evaluation.pair_hash != pair_hash(record.proposal)
    ):
        raise ValueError("B-completion metrics, trajectory, or hashes do not recompute")
    metrics = evaluation.metrics
    return BCompletionRecordRef(
        parent_id=parent_id,
        agent=agent,
        seed=seed,
        run_id=record.run_id,
        step_index=record.step_index,
        proposal_index=record.proposal_index,
        proposer=record.proposer,
        proposal=record.proposal,
        hardware_hash=evaluation.hardware_hash,
        state_a_geometry_hash=evaluation.state_a_geometry_hash,
        state_b_geometry_hash=evaluation.state_b_geometry_hash,
        pair_hash=evaluation.pair_hash,
        valid_pair_search=metrics.valid_pair_search,
        base_score=metrics.base_score,
        search_score=metrics.search_score,
        worst_reflected_power_fraction=metrics.worst_reflected_power_fraction,
    )


def _seed_support(
    rows: tuple[BCompletionCellRow, ...],
) -> tuple[BCompletionSeedSupport, ...]:
    return tuple(
        BCompletionSeedSupport(
            parent_id=parent_id,
            agent=agent,
            h1_seeds=tuple(
                row.seed
                for row in rows
                if row.parent_id == parent_id and row.agent == agent and row.h1_count > 0
            ),
            h2_seeds=tuple(
                row.seed
                for row in rows
                if row.parent_id == parent_id and row.agent == agent and row.h2_count > 0
            ),
            h1_seed_count=sum(
                row.parent_id == parent_id and row.agent == agent and row.h1_count > 0
                for row in rows
            ),
            h2_seed_count=sum(
                row.parent_id == parent_id and row.agent == agent and row.h2_count > 0
                for row in rows
            ),
        )
        for parent_id in PARENTS
        for agent in AGENTS
    )


def _scientific_endpoint(h1_count: int, h2_count: int) -> ScientificEndpoint:
    if h2_count >= 1:
        return "b_completion_effect_crossing_observed"
    if h1_count >= 1:
        return "b_completion_pair_validity_without_effect_crossing"
    return "no_b_completion_pair_observed"


def _selection_key(
    record: BCompletionRecordRef,
) -> tuple[int, float, str, str, int]:
    return (
        0 if record.h2 else 1,
        record.worst_reflected_power_fraction,
        record.pair_hash,
        record.run_id,
        record.step_index,
    )


def build_b_completion_appendix(
    rows: tuple[BCompletionCellRow, ...],
    records: tuple[BCompletionRecordRef, ...],
    *,
    study_status: str | None = None,
    matrix_exception_type: str | None = None,
    matrix_exception_message: str | None = None,
) -> BCompletionAppendix:
    """Build complete aggregates or an explicitly aggregate-null failure appendix."""

    identities = tuple(
        (record.run_id, record.step_index, record.proposal_index) for record in records
    )
    if len(set(identities)) != len(identities):
        raise ValueError("B-completion accepted record identities are duplicated")
    row_index = {
        (row.parent_id, row.agent, row.seed, row.run_id): row for row in rows
    }
    if len(row_index) != len(rows):
        raise ValueError("B-completion matrix rows are duplicated")
    for record in records:
        key = (record.parent_id, record.agent, record.seed, record.run_id)
        if key not in row_index:
            raise ValueError("B-completion record has no matrix row")
    for row in rows:
        cell_records = tuple(
            record
            for record in records
            if (record.parent_id, record.agent, record.seed, record.run_id)
            == (row.parent_id, row.agent, row.seed, row.run_id)
        )
        if len(cell_records) != row.accepted_count:
            raise ValueError("B-completion cell accepted count does not match records")
        if sum(record.h1 for record in cell_records) != row.h1_count:
            raise ValueError("B-completion cell H1 count does not match records")
        if sum(record.h2 for record in cell_records) != row.h2_count:
            raise ValueError("B-completion cell H2 count does not match records")

    complete = len(rows) == 20 and all(
        row.execution_status == "completed" for row in rows
    )
    if not complete:
        completed_prefix = tuple(
            row.run_id for row in rows if row.execution_status == "completed"
        )
        failed_run_id = next(
            (row.run_id for row in rows if row.execution_status == "execution_failed"),
            None,
        )
        return BCompletionAppendix(
            study_status=study_status or "study_incomplete",
            rows=rows,
            completed_prefix=completed_prefix,
            failed_run_id=failed_run_id,
            matrix_exception_type=matrix_exception_type or "BCompletionMatrixIncomplete",
            matrix_exception_message=matrix_exception_message
            or "the fixed-order matrix did not complete",
        )
    if study_status not in (None, "complete"):
        raise ValueError("complete B-completion matrix cannot use a failure status")
    if len(records) != len(PARENTS) * len(AGENTS) * len(SEEDS) * EVALUATION_BUDGET:
        raise ValueError("complete B-completion matrix lacks 6,000 accepted records")
    h1_records = tuple(record for record in records if record.h1)
    h2_records = tuple(record for record in h1_records if record.h2)
    selection_keys = tuple(_selection_key(record) for record in h1_records)
    if len(set(selection_keys)) != len(selection_keys):
        raise ValueError("descriptive selection key is ambiguous")
    selected = min(h1_records, key=_selection_key) if h1_records else None
    return BCompletionAppendix(
        study_status="complete",
        rows=rows,
        h1_count=len(h1_records),
        h2_count=len(h2_records),
        seed_support=_seed_support(rows),
        scientific_endpoint=_scientific_endpoint(len(h1_records), len(h2_records)),
        selected_hypothesis=selected,
    )


def render_b_completion_report(appendix: BCompletionAppendix) -> str:
    """Render the complete twenty-cell table and claim-limited endpoint."""

    lines = [
        "# B-parent conditional-completion analysis",
        "",
        f"- Study status: `{appendix.study_status}`",
        f"- Scientific endpoint: `{appendix.scientific_endpoint}`",
        "- Verdict ceiling: `insufficient_evidence`",
        "",
        "| Parent | Agent | Seed | Status | Accepted | H1 | H2 |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for row in appendix.rows:
        lines.append(
            f"| {row.parent_id} | {row.agent} | {row.seed} | "
            f"`{row.execution_status}` | {row.accepted_count} | "
            f"{row.h1_count} | {row.h2_count} |"
        )
    if appendix.study_status != "complete":
        lines.extend(
            (
                "",
                f"Terminal evidence: `{appendix.matrix_exception_type}` — "
                f"{appendix.matrix_exception_message}.",
                "Scientific counts, seed support, selected hypothesis, and endpoint "
                "remain null because the fixed matrix did not complete.",
            )
        )
    else:
        assert appendix.h1_count is not None
        assert appendix.h2_count is not None
        assert appendix.seed_support is not None
        lines.extend(
            (
                "",
                f"- H1 accepted records: {appendix.h1_count}",
                f"- H2 accepted records: {appendix.h2_count}",
                "",
                "## Parent-by-agent seed support",
                "",
                "| Parent | Agent | H1 seeds | H2 seeds | Interpretation |",
                "|---|---|---:|---:|---|",
            )
        )
        for item in appendix.seed_support:
            maximum = max(item.h1_seed_count, item.h2_seed_count)
            interpretation = (
                "one-seed fact; not a stability claim"
                if maximum == 1
                else "no supporting seed"
                if maximum == 0
                else f"descriptive support in {maximum}/5 seeds"
            )
            lines.append(
                f"| {item.parent_id} | {item.agent} | {item.h1_seed_count}/5 | "
                f"{item.h2_seed_count}/5 | {interpretation} |"
            )
        selected = appendix.selected_hypothesis
        if selected is not None:
            lines.extend(
                (
                    "",
                    "## Descriptive selected hypothesis",
                    "",
                    f"- Source: `{selected.run_id}` step {selected.step_index}, "
                    f"proposal {selected.proposal_index}",
                    f"- Parent/agent/seed: {selected.parent_id} / {selected.agent} / "
                    f"{selected.seed}",
                    f"- H1/H2: {selected.h1} / {selected.h2}",
                    "- Worst reflected-power fraction: "
                    f"{selected.worst_reflected_power_fraction:.17g}",
                    f"- Pair hash: `{selected.pair_hash}`",
                    f"- Hardware hash: `{selected.hardware_hash}`",
                    "- Proposal: `"
                    + json.dumps(
                        selected.proposal.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                    + "`",
                )
            )
    lines.extend(
        (
            "",
            "Random is the comparison baseline. This is an NEC2-only descriptive "
            "outcome; independent-solver confirmation requires a separate "
            "preregistration.",
            "",
        )
    )
    return "\n".join(lines)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_b_completion_outputs(
    output_dir: Path,
    appendix: BCompletionAppendix,
) -> None:
    """Atomically write LF-only appendix and report evidence."""

    appendix_bytes = (
        json.dumps(
            appendix.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    report_bytes = render_b_completion_report(appendix).encode("utf-8")
    if b"\r" in appendix_bytes or b"\r" in report_bytes:
        raise ValueError("B-completion outputs must be LF-only")
    _atomic_write(output_dir / "appendix.json", appendix_bytes)
    _atomic_write(output_dir / "report.md", report_bytes)


def sha256_file(path: Path) -> str:
    """Return a source-addressing digest for one analysis artifact."""

    return hashlib.sha256(path.read_bytes()).hexdigest()
