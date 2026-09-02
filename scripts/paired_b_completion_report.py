"""Generate the frozen B-parent conditional-completion appendix and report."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from yaf_ai.analysis.paired_b_completion import (
    EVALUATION_BUDGET,
    MAPPING_VERSION,
    SEEDS,
    SPEC_REVISION,
    STUDY_ID,
    Agent,
    BCompletionAppendix,
    BCompletionCellRow,
    BCompletionRecordRef,
    ParentId,
    build_b_completion_appendix,
    expected_run_id,
    record_ref,
    write_b_completion_outputs,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRejectionRecord,
    PairedRunSummary,
    _load_paired_events,
)

OUTPUT_DIRECTORY = Path(
    "artifacts/analysis/semifinal-paired-b-completion-v1"
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class MatrixFailureEvidence(BaseModel):
    """Frozen terminal evidence accepted by the failure-report branch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study_id: str = STUDY_ID
    study_status: str = Field(min_length=1)
    failed_run_id: str | None = None
    completed_prefix: tuple[str, ...] = ()
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    proposal_attempts: int = Field(default=0, ge=0)
    partial_log_sha256: str = EMPTY_SHA256
    partial_log_bytes: int = Field(default=0, ge=0)
    partial_log_lines: int = Field(default=0, ge=0)
    exception_type: str = Field(
        min_length=1,
        validation_alias=AliasChoices("exception_type", "exception_class"),
    )
    exception_message: str = Field(min_length=1)
    expected_b_hashes: dict[str, str] | None = None
    actual_b_hashes: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        if len(self.partial_log_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.partial_log_sha256
        ):
            raise ValueError("failure partial-log SHA-256 is invalid")
        if self.schema_version != 1 or self.study_id != STUDY_ID:
            raise ValueError("failure schema identity changed")
        if self.study_status == "support_certificate_failed":
            if (
                self.failed_run_id is not None
                or self.completed_prefix
                or self.accepted_count != 0
                or self.rejected_count != 0
                or self.proposal_attempts != 0
                or self.partial_log_sha256 != EMPTY_SHA256
                or self.partial_log_bytes != 0
                or self.partial_log_lines != 0
            ):
                raise ValueError("certificate failure cannot carry matrix evidence")
        elif self.failed_run_id is None:
            raise ValueError("terminal matrix failure lacks failed_run_id")
        if (self.expected_b_hashes is None) != (self.actual_b_hashes is None):
            raise ValueError("failure B hashes must provide expected and actual values")
        return self


def _canonical_config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_config(
    config: dict[str, Any],
    parent_id: ParentId,
    agent: Agent,
    seed: int,
    run_id: str,
) -> None:
    expected: dict[str, object] = {
        "run_id": run_id,
        "agent": agent,
        "seed": seed,
        "evaluation_budget": EVALUATION_BUDGET,
        "study_id": STUDY_ID,
        "spec_revision": SPEC_REVISION,
        "mapping_version": MAPPING_VERSION,
        "parent_id": parent_id,
        "parent_code": 1 if parent_id == "p01" else 2,
        "agent_code": 3 if agent == "random-b-completion" else 4,
        "anchor_released": False,
        "openems_cross_check_authorized": False,
        "rng_version": "numpy-pcg64-seedsequence-v1",
        "stream_format_version": "canonical-json-float-hex-lf-v1",
        "rng_stream_revision": 1,
        "max_consecutive_rejections": 100,
        "max_total_proposal_attempts": EVALUATION_BUDGET,
    }
    changed = {
        key: (config.get(key), value)
        for key, value in expected.items()
        if config.get(key) != value
    }
    if changed:
        raise ValueError(f"B-completion summary config fields changed: {changed}")


def _read_lf_bytes(path: Path) -> bytes:
    payload = path.read_bytes()
    if b"\r" in payload or (payload and not payload.endswith(b"\n")):
        raise ValueError(f"B-completion evidence is not LF-only: {path}")
    return payload


def _load_completed_cell(
    runs_root: Path,
    parent_id: ParentId,
    agent: Agent,
    seed: int,
) -> tuple[BCompletionCellRow, tuple[BCompletionRecordRef, ...]]:
    run_id = expected_run_id(parent_id, agent, seed)
    run_directory = runs_root / run_id
    log_path = run_directory / "log.jsonl"
    summary_path = run_directory / "summary.json"
    if not log_path.is_file() or not summary_path.is_file():
        raise FileNotFoundError(f"missing completed B-completion run: {run_id}")
    log_bytes = _read_lf_bytes(log_path)
    summary_bytes = _read_lf_bytes(summary_path)
    events = _load_paired_events(log_path)
    if (
        len(events) != EVALUATION_BUDGET
        or any(not isinstance(event, PairedEvaluationRecord) for event in events)
    ):
        raise ValueError("completed B-completion log is not 300 accepted records")
    evaluations = tuple(
        event for event in events if isinstance(event, PairedEvaluationRecord)
    )
    if tuple(event.step_index for event in evaluations) != tuple(
        range(EVALUATION_BUDGET)
    ) or tuple(event.proposal_index for event in evaluations) != tuple(
        range(EVALUATION_BUDGET)
    ):
        raise ValueError("completed B-completion log indices changed")
    records = tuple(
        record_ref(event, parent_id, agent, seed) for event in evaluations
    )
    if any(not event.evaluation.trajectory.valid for event in evaluations):
        raise ValueError("completed B-completion log contains an invalid trajectory")

    summary = PairedRunSummary.model_validate_json(summary_bytes)
    _validate_config(summary.config, parent_id, agent, seed, run_id)
    if summary.config_hash != _canonical_config_hash(summary.config):
        raise ValueError("B-completion summary config hash does not recompute")
    if (
        summary.run_id != run_id
        or summary.seed != seed
        or summary.steps_completed != EVALUATION_BUDGET
        or summary.evaluation_budget != EVALUATION_BUDGET
        or summary.rejected_proposals != 0
        or summary.proposal_attempts != EVALUATION_BUDGET
        or summary.solver_mode_counts != {"subprocess": 2 * EVALUATION_BUDGET}
        or summary.status != "completed"
        or summary.termination_reason
        != "accepted paired-evaluation budget completed"
        or summary.verdict_ceiling != "insufficient_evidence"
    ):
        raise ValueError("B-completion summary violates its sole legal terminal")
    row = BCompletionCellRow(
        parent_id=parent_id,
        agent=agent,
        seed=seed,
        run_id=run_id,
        execution_status="completed",
        source_status=summary.status,
        accepted_count=len(records),
        rejected_count=0,
        proposal_attempts=summary.proposal_attempts,
        solver_mode_counts=summary.solver_mode_counts,
        h1_count=sum(record.h1 for record in records),
        h2_count=sum(record.h2 for record in records),
        log_sha256=hashlib.sha256(log_bytes).hexdigest(),
        summary_sha256=hashlib.sha256(summary_bytes).hexdigest(),
    )
    return row, records


def _not_run_row(
    parent_id: ParentId,
    agent: Agent,
    seed: int,
) -> BCompletionCellRow:
    return BCompletionCellRow(
        parent_id=parent_id,
        agent=agent,
        seed=seed,
        run_id=expected_run_id(parent_id, agent, seed),
        execution_status="not_run_after_matrix_abort",
        accepted_count=0,
        rejected_count=0,
        proposal_attempts=0,
        solver_mode_counts={},
        h1_count=0,
        h2_count=0,
    )


def _matrix() -> tuple[tuple[ParentId, Agent, int], ...]:
    parent_ids: tuple[ParentId, ...] = ("p01", "p02")
    agents: tuple[Agent, ...] = ("random-b-completion", "es-b-completion")
    return tuple(
        (parent_id, agent, seed)
        for parent_id in parent_ids
        for agent in agents
        for seed in SEEDS
    )


def _load_failure(
    repo_root: Path,
    failure_path: Path,
) -> BCompletionAppendix:
    failure_bytes = _read_lf_bytes(failure_path)
    failure = MatrixFailureEvidence.model_validate_json(failure_bytes)
    matrix = _matrix()
    expected_ids = tuple(
        expected_run_id(parent_id, agent, seed)
        for parent_id, agent, seed in matrix
    )
    prefix_length = len(failure.completed_prefix)
    if failure.completed_prefix != expected_ids[:prefix_length]:
        raise ValueError("failure completed prefix differs from frozen matrix order")
    rows: list[BCompletionCellRow] = []
    records: list[BCompletionRecordRef] = []
    runs_root = repo_root / "runs"
    for parent_id, agent, seed in matrix[:prefix_length]:
        row, cell_records = _load_completed_cell(
            runs_root,
            parent_id,
            agent,
            seed,
        )
        rows.append(row)
        records.extend(cell_records)
    if failure.study_status == "support_certificate_failed":
        rows.extend(
            _not_run_row(parent_id, agent, seed)
            for parent_id, agent, seed in matrix
        )
        return build_b_completion_appendix(
            tuple(rows),
            tuple(records),
            study_status=failure.study_status,
            matrix_exception_type=failure.exception_type,
            matrix_exception_message=failure.exception_message,
        )
    if prefix_length >= len(matrix):
        raise ValueError("matrix failure cannot follow a complete 20-run prefix")
    failed_identity = matrix[prefix_length]
    failed_expected = expected_ids[prefix_length]
    if failure.failed_run_id != failed_expected:
        raise ValueError("failure run ID is not the next frozen matrix cell")
    parent_id, agent, seed = failed_identity
    partial_path = runs_root / failed_expected / "log.jsonl"
    partial_bytes = partial_path.read_bytes() if partial_path.is_file() else b""
    if b"\r" in partial_bytes or (
        partial_bytes and not partial_bytes.endswith(b"\n")
    ):
        raise ValueError("failure partial log is not LF-only")
    partial_sha = hashlib.sha256(partial_bytes).hexdigest()
    partial_lines = len(partial_bytes.splitlines())
    if (
        partial_sha != failure.partial_log_sha256
        or len(partial_bytes) != failure.partial_log_bytes
        or partial_lines != failure.partial_log_lines
    ):
        raise ValueError("failure partial-log evidence does not match persisted bytes")
    events = _load_paired_events(partial_path) if partial_path.is_file() else ()
    evaluations = tuple(
        event for event in events if isinstance(event, PairedEvaluationRecord)
    )
    rejections = tuple(
        event for event in events if isinstance(event, PairedRejectionRecord)
    )
    if (
        len(evaluations) != failure.accepted_count
        or len(rejections) != failure.rejected_count
    ):
        raise ValueError("failure accepted/rejected counts do not match partial log")
    partial_records = tuple(
        record_ref(event, parent_id, agent, seed) for event in evaluations
    )
    if any(not event.evaluation.trajectory.valid for event in evaluations):
        raise ValueError("failure partial log contains an invalid accepted trajectory")
    records.extend(partial_records)
    rows.append(
        BCompletionCellRow(
            parent_id=parent_id,
            agent=agent,
            seed=seed,
            run_id=failed_expected,
            execution_status="execution_failed",
            source_status=failure.study_status,
            accepted_count=len(partial_records),
            rejected_count=len(rejections),
            proposal_attempts=failure.proposal_attempts,
            solver_mode_counts={"subprocess": 2 * len(partial_records)},
            h1_count=sum(record.h1 for record in partial_records),
            h2_count=sum(record.h2 for record in partial_records),
            log_sha256=partial_sha,
            partial_log_bytes=len(partial_bytes),
            partial_log_lines=partial_lines,
            expected_b_hashes=failure.expected_b_hashes,
            actual_b_hashes=failure.actual_b_hashes,
            exception_type=failure.exception_type,
            exception_message=failure.exception_message,
        )
    )
    rows.extend(
        _not_run_row(next_parent, next_agent, next_seed)
        for next_parent, next_agent, next_seed in matrix[prefix_length + 1 :]
    )
    return build_b_completion_appendix(
        tuple(rows),
        tuple(records),
        study_status=failure.study_status,
        matrix_exception_type=failure.exception_type,
        matrix_exception_message=failure.exception_message,
    )


def load_b_completion_evidence(
    repo_root: Path,
    failure_path: Path | None = None,
) -> BCompletionAppendix:
    """Load the exact success matrix or one preregistered terminal failure."""

    root = repo_root.resolve()
    if failure_path is not None:
        return _load_failure(root, failure_path.resolve())
    rows: list[BCompletionCellRow] = []
    records: list[BCompletionRecordRef] = []
    for parent_id, agent, seed in _matrix():
        row, cell_records = _load_completed_cell(
            root / "runs",
            parent_id,
            agent,
            seed,
        )
        rows.append(row)
        records.extend(cell_records)
    return build_b_completion_appendix(tuple(rows), tuple(records))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--failure-json",
        type=Path,
        help="Optional frozen terminal matrix_failure.json or certificate failure.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    failure_path: Path | None = args.failure_json
    if failure_path is not None and not failure_path.is_absolute():
        failure_path = root / failure_path
    appendix = load_b_completion_evidence(root, failure_path)
    output = root / OUTPUT_DIRECTORY
    write_b_completion_outputs(output, appendix)
    print(
        f"B completion {appendix.study_status}: rows={len(appendix.rows)}; "
        f"records={sum(row.accepted_count for row in appendix.rows)}; "
        f"appendix={output / 'appendix.json'}; report={output / 'report.md'}"
    )
    return 0 if appendix.study_status == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
