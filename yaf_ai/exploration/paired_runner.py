"""Crash-resumable, LF-only runner for frozen paired-state proposals."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_meander import (
    MAX_CONSECUTIVE_REJECTIONS,
    MAX_TOTAL_PROPOSAL_ATTEMPTS,
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    AnchorNotReleasedError,
    PairedEvaluation,
    PairedProposal,
    PairedSolver,
    SearchCurve,
    audit_trajectory,
    build_state_geometry,
    hardware_hash,
    pair_hash,
    score_paired_curves,
    state_geometry_hash,
)


class PairedRunError(RuntimeError):
    """Raised when persisted paired-run state violates the frozen config."""


class PairedRunConfig(BaseModel):
    """Immutable run definition that enters the summary config hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    agent: Literal["random", "es-cold", "es-warm", "manual"]
    seed: int
    evaluation_budget: int = Field(gt=0)
    anchor_released: bool
    openems_cross_check_authorized: Literal[False] = False
    preregistration_commit: str = Field(min_length=7)
    execution_commit: str | None = None
    budget_source_summary_sha256: str | None = None
    budget_source_config_hash: str | None = None
    manual_baseline_commit: str | None = None
    warm_parent_run_id: str | None = None
    warm_parent_pair_hash: str | None = None
    warm_parent_document_sha256: str | None = None
    warm_parent_hardware_hash: str | None = None
    warm_parent_state_a_geometry_hash: str | None = None
    warm_parent_state_b_geometry_hash: str | None = None
    warm_parent_step_index: int | None = Field(default=None, ge=0)
    warm_parent_hardware_grid_index: int | None = Field(default=None, ge=0)
    warm_parent_pair_grid_index: int | None = Field(default=None, ge=0)
    warm_parent_search_score: float | None = None
    max_consecutive_rejections: int = MAX_CONSECUTIVE_REJECTIONS
    max_total_proposal_attempts: int = MAX_TOTAL_PROPOSAL_ATTEMPTS

    @model_validator(mode="after")
    def validate_warm_provenance(self) -> Self:
        """Require complete committed provenance for the warm arm only."""

        provenance = (
            self.manual_baseline_commit,
            self.warm_parent_run_id,
            self.warm_parent_pair_hash,
            self.warm_parent_document_sha256,
            self.warm_parent_hardware_hash,
            self.warm_parent_state_a_geometry_hash,
            self.warm_parent_state_b_geometry_hash,
            self.warm_parent_step_index,
            self.warm_parent_hardware_grid_index,
            self.warm_parent_pair_grid_index,
            self.warm_parent_search_score,
        )
        if self.agent == "es-warm" and any(value is None for value in provenance):
            raise ValueError("es-warm requires committed manual-parent provenance")
        if self.agent != "es-warm" and any(value is not None for value in provenance):
            raise ValueError("only es-warm may carry manual-parent provenance")
        batch_provenance = (
            self.execution_commit,
            self.budget_source_summary_sha256,
            self.budget_source_config_hash,
        )
        if any(value is not None for value in batch_provenance) and any(
            value is None for value in batch_provenance
        ):
            raise ValueError("batch execution provenance must be all present or all absent")
        return self


class PairedRunState(BaseModel):
    """Atomically persisted progress used to resume without duplicate rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    run_id: str
    config_hash: str
    next_proposal_index: int = Field(ge=0)
    proposal_attempts: int = Field(ge=0)
    consecutive_rejections: int = Field(ge=0)
    rejected_proposals: int = Field(ge=0)
    evaluations_completed: int = Field(ge=0)
    solver_mode_counts: dict[str, int]


class PairedEvaluationRecord(BaseModel):
    """One source-addressed accepted evaluation row in log.jsonl."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    event_type: Literal["paired_evaluation"] = "paired_evaluation"
    run_id: str
    step_index: int = Field(ge=0)
    proposal_index: int = Field(ge=0)
    timestamp: datetime
    proposer: str
    proposal: PairedProposal
    evaluation: PairedEvaluation
    hardware_grid_index: int | None = Field(default=None, ge=0)
    pair_grid_index: int | None = Field(default=None, ge=0)


class PairedRejectionRecord(BaseModel):
    """One geometry-only rejection that consumes no evaluation budget."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    event_type: Literal["paired_rejection"] = "paired_rejection"
    run_id: str
    proposal_index: int = Field(ge=0)
    timestamp: datetime
    proposer: str
    proposal: PairedProposal
    reason: str
    budget_remaining: int = Field(ge=0)


RunStatus = Literal[
    "completed",
    "anchor_not_released",
    "insufficient_feasible_proposals",
    "proposal_sequence_exhausted",
]


class PairedRunSummary(BaseModel):
    """Archive-compatible terminal summary for one paired run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    run_id: str
    started_at: datetime
    finished_at: datetime
    seed: int
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = Field(ge=0)
    evaluation_budget: int = Field(gt=0)
    solver_mode_counts: dict[str, int]
    rejected_proposals: int = Field(ge=0)
    proposal_attempts: int = Field(ge=0)
    status: RunStatus
    termination_reason: str
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"


PREFLIGHT_RUN_ID_PREFIX = "semifinal-paired-budget-preflight"
MANUAL_BASELINE_RUN_ID_PREFIX = "semifinal-paired-manual-baseline"
AGENT_CANDIDATE_EXCLUDED_PREFIXES = (
    PREFLIGHT_RUN_ID_PREFIX,
    MANUAL_BASELINE_RUN_ID_PREFIX,
)


class FrozenCandidate(BaseModel):
    """One NEC2-only candidate frozen before any openEMS result exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    step_index: int = Field(ge=0)
    proposer: str
    hardware_hash: str
    state_a_geometry_hash: str
    state_b_geometry_hash: str
    pair_hash: str
    base_score: float
    valid_pair_search: bool
    positive_eligible: bool


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _config_hash(config: PairedRunConfig) -> str:
    return hashlib.sha256(_canonical_bytes(config.model_dump(mode="json"))).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        ).encode("utf-8")
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    with path.open("ab") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def _initial_state(config: PairedRunConfig) -> PairedRunState:
    return PairedRunState(
        run_id=config.run_id,
        config_hash=_config_hash(config),
        next_proposal_index=0,
        proposal_attempts=0,
        consecutive_rejections=0,
        rejected_proposals=0,
        evaluations_completed=0,
        solver_mode_counts={},
    )


def _load_state(
    path: Path,
    config: PairedRunConfig,
) -> PairedRunState:
    if not path.is_file():
        return _initial_state(config)
    try:
        state = PairedRunState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PairedRunError(f"cannot load paired run state: {error}") from error
    expected = _config_hash(config)
    if state.run_id != config.run_id or state.config_hash != expected:
        raise PairedRunError("persisted paired state belongs to another config")
    return state


def _load_summary(
    path: Path,
    config: PairedRunConfig,
) -> PairedRunSummary | None:
    if not path.is_file():
        return None
    try:
        summary = PairedRunSummary.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PairedRunError(f"cannot load paired summary: {error}") from error
    if summary.config_hash != _config_hash(config):
        raise PairedRunError("persisted paired summary belongs to another config")
    return summary


def _mode_counts(
    state: PairedRunState,
    curves: Sequence[SearchCurve],
) -> dict[str, int]:
    counts = dict(state.solver_mode_counts)
    for curve in curves:
        counts[curve.solver_mode] = counts.get(curve.solver_mode, 0) + 1
    return counts


def _evaluation(
    proposal: PairedProposal,
    state_a_curve: SearchCurve,
    state_b_curve: SearchCurve,
) -> PairedEvaluation:
    trajectory = audit_trajectory(proposal)
    if not trajectory.valid:
        raise PairedRunError("accepted proposal no longer passes trajectory audit")
    geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
    geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
    return PairedEvaluation(
        hardware_hash=hardware_hash(proposal.hardware),
        state_a_geometry_hash=state_geometry_hash(
            proposal.hardware,
            proposal.state_a,
            geometry_a,
        ),
        state_b_geometry_hash=state_geometry_hash(
            proposal.hardware,
            proposal.state_b,
            geometry_b,
        ),
        pair_hash=pair_hash(proposal),
        metrics=score_paired_curves(state_a_curve, state_b_curve),
        trajectory=trajectory,
        state_a_curve=state_a_curve,
        state_b_curve=state_b_curve,
    )


def _summary(
    config: PairedRunConfig,
    state: PairedRunState,
    started_at: datetime,
    status: RunStatus,
    reason: str,
) -> PairedRunSummary:
    return PairedRunSummary(
        run_id=config.run_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        seed=config.seed,
        config_hash=_config_hash(config),
        config=config.model_dump(mode="json"),
        steps_completed=state.evaluations_completed,
        evaluation_budget=config.evaluation_budget,
        solver_mode_counts=state.solver_mode_counts,
        rejected_proposals=state.rejected_proposals,
        proposal_attempts=state.proposal_attempts,
        status=status,
        termination_reason=reason,
    )


async def run_paired_sequence(
    *,
    config: PairedRunConfig,
    proposals: Sequence[PairedProposal],
    solver: PairedSolver,
    runs_root: Path,
) -> PairedRunSummary:
    """Evaluate a deterministic sequence with atomic resume after every row."""

    run_directory = runs_root / config.run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    summary_path = run_directory / "summary.json"
    existing = _load_summary(summary_path, config)
    if existing is not None:
        if existing.status == "anchor_not_released":
            raise AnchorNotReleasedError(existing.termination_reason)
        return existing

    log_path = run_directory / "log.jsonl"
    log_path.touch(exist_ok=True)
    state_path = run_directory / "state.json"
    state = _load_state(state_path, config)
    started_at = datetime.now(UTC)

    while (
        state.evaluations_completed < config.evaluation_budget
        and state.next_proposal_index < len(proposals)
    ):
        if (
            state.proposal_attempts >= config.max_total_proposal_attempts
            or state.consecutive_rejections >= config.max_consecutive_rejections
        ):
            summary = _summary(
                config,
                state,
                started_at,
                "insufficient_feasible_proposals",
                "the frozen proposal-attempt limit was reached",
            )
            _write_json(summary_path, summary.model_dump(mode="json"))
            return summary

        proposal_index = state.next_proposal_index
        proposal = proposals[proposal_index]
        trajectory = audit_trajectory(proposal)
        if not trajectory.valid:
            rejection_record = PairedRejectionRecord(
                run_id=config.run_id,
                proposal_index=proposal_index,
                timestamp=datetime.now(UTC),
                proposer=proposal.proposer,
                proposal=proposal,
                reason=trajectory.rejection_reason or "trajectory audit failed",
                budget_remaining=(config.evaluation_budget - state.evaluations_completed),
            )
            _append_jsonl(log_path, rejection_record.model_dump(mode="json"))
            state = state.model_copy(
                update={
                    "next_proposal_index": proposal_index + 1,
                    "proposal_attempts": state.proposal_attempts + 1,
                    "consecutive_rejections": state.consecutive_rejections + 1,
                    "rejected_proposals": state.rejected_proposals + 1,
                }
            )
            _write_json(state_path, state.model_dump(mode="json"))
            continue

        geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
        geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
        curve_a = await solver(
            geometry_a,
            "A",
            STATE_A_FREQUENCIES_HZ,
        )
        curve_b = await solver(
            geometry_b,
            "B",
            STATE_B_FREQUENCIES_HZ,
        )
        evaluation = _evaluation(proposal, curve_a, curve_b)
        evaluation_record = PairedEvaluationRecord(
            run_id=config.run_id,
            step_index=state.evaluations_completed,
            proposal_index=proposal_index,
            timestamp=datetime.now(UTC),
            proposer=proposal.proposer,
            proposal=proposal,
            evaluation=evaluation,
        )
        _append_jsonl(log_path, evaluation_record.model_dump(mode="json"))
        state = state.model_copy(
            update={
                "next_proposal_index": proposal_index + 1,
                "proposal_attempts": state.proposal_attempts + 1,
                "consecutive_rejections": 0,
                "evaluations_completed": state.evaluations_completed + 1,
                "solver_mode_counts": _mode_counts(
                    state,
                    (curve_a, curve_b),
                ),
            }
        )
        _write_json(state_path, state.model_dump(mode="json"))

    if state.evaluations_completed == config.evaluation_budget:
        status: RunStatus = "completed"
        reason = "accepted paired-evaluation budget completed"
    else:
        status = "proposal_sequence_exhausted"
        reason = "deterministic proposal sequence ended before the budget"
    summary = _summary(config, state, started_at, status, reason)
    _write_json(summary_path, summary.model_dump(mode="json"))
    return summary



class PairedAdaptiveProposer(Protocol):
    """Deterministic proposer contract with replayable rejection semantics."""

    def propose(self) -> PairedProposal:
        """Return the next proposal without mutating adaptation state."""

    def observe(self, evaluation: PairedEvaluation) -> None:
        """Consume one completed paired evaluation."""

    def reject(self, proposal: PairedProposal) -> None:
        """Consume one geometry rejection without solver feedback."""


PairedEvent = PairedEvaluationRecord | PairedRejectionRecord


def _load_paired_events(log_path: Path) -> tuple[PairedEvent, ...]:
    events: list[PairedEvent] = []
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            if payload.get("event_type") == "paired_evaluation":
                events.append(PairedEvaluationRecord.model_validate(payload))
            elif payload.get("event_type") == "paired_rejection":
                events.append(PairedRejectionRecord.model_validate(payload))
            else:
                raise ValueError("unknown paired event type")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PairedRunError(f"cannot load paired event log: {error}") from error
    return tuple(events)


def _proposal_identity(proposal: PairedProposal) -> bytes:
    return _canonical_bytes(proposal.model_dump(mode="json"))


def _state_from_events(
    config: PairedRunConfig,
    events: Sequence[PairedEvent],
) -> PairedRunState:
    state = _initial_state(config)
    for event in events:
        if event.run_id != config.run_id:
            raise PairedRunError("paired event belongs to another run")
        if event.proposal_index != state.next_proposal_index:
            raise PairedRunError("paired event proposal index is not contiguous")
        if isinstance(event, PairedRejectionRecord):
            state = state.model_copy(
                update={
                    "next_proposal_index": state.next_proposal_index + 1,
                    "proposal_attempts": state.proposal_attempts + 1,
                    "consecutive_rejections": state.consecutive_rejections + 1,
                    "rejected_proposals": state.rejected_proposals + 1,
                }
            )
        else:
            if event.step_index != state.evaluations_completed:
                raise PairedRunError("paired evaluation step index is not contiguous")
            state = state.model_copy(
                update={
                    "next_proposal_index": state.next_proposal_index + 1,
                    "proposal_attempts": state.proposal_attempts + 1,
                    "consecutive_rejections": 0,
                    "evaluations_completed": state.evaluations_completed + 1,
                    "solver_mode_counts": _mode_counts(
                        state,
                        (event.evaluation.state_a_curve, event.evaluation.state_b_curve),
                    ),
                }
            )
    return state


def _replay_proposer(
    proposer: PairedAdaptiveProposer,
    events: Sequence[PairedEvent],
) -> None:
    for event in events:
        generated = proposer.propose()
        if _proposal_identity(generated) != _proposal_identity(event.proposal):
            raise PairedRunError("adaptive proposer replay drifted from the audit log")
        if isinstance(event, PairedRejectionRecord):
            proposer.reject(generated)
        else:
            proposer.observe(event.evaluation)


async def run_paired_adaptive(
    *,
    config: PairedRunConfig,
    proposer: PairedAdaptiveProposer,
    solver: PairedSolver,
    runs_root: Path,
) -> PairedRunSummary:
    """Run a replayable adaptive proposer with geometry-only free rejections."""

    run_directory = runs_root / config.run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    summary_path = run_directory / "summary.json"
    existing = _load_summary(summary_path, config)
    if existing is not None:
        if existing.status == "anchor_not_released":
            raise AnchorNotReleasedError(existing.termination_reason)
        return existing

    log_path = run_directory / "log.jsonl"
    log_path.touch(exist_ok=True)
    state_path = run_directory / "state.json"
    if state_path.is_file():
        _load_state(state_path, config)
    events = _load_paired_events(log_path)
    state = _state_from_events(config, events)
    _replay_proposer(proposer, events)
    _write_json(state_path, state.model_dump(mode="json"))
    started_at = datetime.now(UTC)

    while state.evaluations_completed < config.evaluation_budget:
        if (
            state.proposal_attempts >= config.max_total_proposal_attempts
            or state.consecutive_rejections >= config.max_consecutive_rejections
        ):
            summary = _summary(
                config,
                state,
                started_at,
                "insufficient_feasible_proposals",
                "the frozen proposal-attempt limit was reached",
            )
            _write_json(summary_path, summary.model_dump(mode="json"))
            return summary

        proposal_index = state.next_proposal_index
        proposal = proposer.propose()
        trajectory = audit_trajectory(proposal)
        if not trajectory.valid:
            rejection_record = PairedRejectionRecord(
                run_id=config.run_id,
                proposal_index=proposal_index,
                timestamp=datetime.now(UTC),
                proposer=proposal.proposer,
                proposal=proposal,
                reason=trajectory.rejection_reason or "trajectory audit failed",
                budget_remaining=config.evaluation_budget - state.evaluations_completed,
            )
            _append_jsonl(log_path, rejection_record.model_dump(mode="json"))
            proposer.reject(proposal)
            state = state.model_copy(
                update={
                    "next_proposal_index": proposal_index + 1,
                    "proposal_attempts": state.proposal_attempts + 1,
                    "consecutive_rejections": state.consecutive_rejections + 1,
                    "rejected_proposals": state.rejected_proposals + 1,
                }
            )
            _write_json(state_path, state.model_dump(mode="json"))
            continue

        geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
        geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
        curve_a = await solver(geometry_a, "A", STATE_A_FREQUENCIES_HZ)
        curve_b = await solver(geometry_b, "B", STATE_B_FREQUENCIES_HZ)
        evaluation = _evaluation(proposal, curve_a, curve_b)
        evaluation_record = PairedEvaluationRecord(
            run_id=config.run_id,
            step_index=state.evaluations_completed,
            proposal_index=proposal_index,
            timestamp=datetime.now(UTC),
            proposer=proposal.proposer,
            proposal=proposal,
            evaluation=evaluation,
        )
        _append_jsonl(log_path, evaluation_record.model_dump(mode="json"))
        proposer.observe(evaluation)
        state = state.model_copy(
            update={
                "next_proposal_index": proposal_index + 1,
                "proposal_attempts": state.proposal_attempts + 1,
                "consecutive_rejections": 0,
                "evaluations_completed": state.evaluations_completed + 1,
                "solver_mode_counts": _mode_counts(state, (curve_a, curve_b)),
            }
        )
        _write_json(state_path, state.model_dump(mode="json"))

    summary = _summary(
        config,
        state,
        started_at,
        "completed",
        "accepted paired-evaluation budget completed",
    )
    _write_json(summary_path, summary.model_dump(mode="json"))
    return summary

def load_paired_evaluations(
    log_path: Path,
) -> tuple[PairedEvaluationRecord, ...]:
    """Read accepted rows only; rejection rows remain independently auditable."""

    records: list[PairedEvaluationRecord] = []
    try:
        for line in log_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            if payload.get("event_type") == "paired_evaluation":
                records.append(PairedEvaluationRecord.model_validate(payload))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PairedRunError(f"cannot load paired evaluation log: {error}") from error
    return tuple(records)


def freeze_candidate(
    records: Sequence[PairedEvaluationRecord],
) -> FrozenCandidate:
    """Apply eligibility then the frozen NEC2-only deterministic ordering."""

    eligible_records = [
        record
        for record in records
        if not any(
            record.run_id == prefix or record.run_id.startswith(prefix + "-")
            for prefix in AGENT_CANDIDATE_EXCLUDED_PREFIXES
        )
    ]
    if not eligible_records:
        raise PairedRunError("candidate pool is empty after non-agent exclusion")
    valid = [
        record
        for record in eligible_records
        if record.evaluation.metrics.valid_pair_search
    ]
    positive_eligible = bool(valid)
    pool = valid if valid else eligible_records
    selected = min(
        pool,
        key=lambda record: (
            -record.evaluation.metrics.base_score,
            record.evaluation.hardware_hash,
            record.run_id,
            record.step_index,
        ),
    )
    evaluation = selected.evaluation
    return FrozenCandidate(
        run_id=selected.run_id,
        step_index=selected.step_index,
        proposer=selected.proposer,
        hardware_hash=evaluation.hardware_hash,
        state_a_geometry_hash=evaluation.state_a_geometry_hash,
        state_b_geometry_hash=evaluation.state_b_geometry_hash,
        pair_hash=evaluation.pair_hash,
        base_score=evaluation.metrics.base_score,
        valid_pair_search=evaluation.metrics.valid_pair_search,
        positive_eligible=positive_eligible,
    )
