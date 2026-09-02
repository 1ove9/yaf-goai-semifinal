"""Deterministic analysis and reporting for exact-support Stage B."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_feasible_agents import StratifiedAgentDiagnostics
from yaf_ai.exploration.paired_feasible_batch import (
    AGENTS as EXECUTION_AGENTS,
)
from yaf_ai.exploration.paired_feasible_batch import (
    MATRIX,
    StageBAgent,
    StageBFrozenInputs,
    StageBRunConfig,
    build_stage_b_config,
    build_stage_b_proposer,
)
from yaf_ai.exploration.paired_meander import (
    audit_trajectory,
    hardware_hash,
    pair_hash,
    score_paired_curves,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRejectionRecord,
    PairedRunSummary,
    _config_hash,
    _load_paired_events,
    _replay_proposer,
    _state_from_events,
)

STUDY_ID = "semifinal-paired-feasibility-stratified-exact-v2"
SPEC_REVISION = "2.0-exact-nominal-support"
MAPPING_VERSION = "conditional-exact-feasible-turn-v2"
L_REQUIRED = 0.19394054289730642
SEEDS = (101, 202, 303, 404, 505)
TURNS = (3, 4, 5, 6)
AGENTS = ("random", "es")
EVALUATION_BUDGET = 600
QUOTA_PER_TURN = 150
OUTPUT_DIRECTORY = Path(
    "artifacts/analysis/semifinal-feasibility-stratified-v2-stage-b"
)

Agent = Literal["random", "es"]
CellStatus = Literal["completed", "execution_failed", "not_run_after_matrix_abort"]
ScientificEndpoint = Literal[
    "turn_stratified_cross_seed_gate_crossing",
    "turn_stratified_seed_local_gate_crossing",
    "no_gate_crossing_observed_under_frozen_stratified_study",
]


def _is_sha256(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def expected_run_id(agent: Agent, seed: int) -> str:
    """Return the sole preregistered run ID for a Stage-B cell."""

    return f"semifinal-paired-stratified-v2-{agent}-s{seed}"


class StageBRecordRef(BaseModel):
    """One source-addressed accepted Stage-B record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    agent: Agent
    seed: int
    turn: int
    step_index: int = Field(ge=0)
    proposal_index: int = Field(ge=0)
    hardware_hash: str
    pair_hash: str
    valid_pair_search: bool
    base_score: float
    worst_reflected_power_fraction: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        if not _is_sha256(self.hardware_hash) or not _is_sha256(self.pair_hash):
            raise ValueError("Stage-B record hashes must be lowercase SHA-256")
        return self

    @property
    def passes(self) -> bool:
        """Apply the unchanged exact-v2 NEC2 gate."""

        return self.valid_pair_search and self.worst_reflected_power_fraction <= L_REQUIRED


class StageBTurnRow(BaseModel):
    """One turn stratum within a completed or partial cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn: int
    accepted_count: int = Field(ge=0)
    unique_candidate_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    best_valid: StageBRecordRef | None = None
    best_gate_crossing: StageBRecordRef | None = None
    diagnostic_top: StageBRecordRef | None = None

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if self.turn not in TURNS:
            raise ValueError("Stage-B turn lies outside the frozen strata")
        if (
            self.unique_candidate_count > self.accepted_count
            or self.valid_count > self.unique_candidate_count
            or self.pass_count > self.valid_count
        ):
            raise ValueError("Stage-B turn counts are inconsistent")
        if (self.best_valid is None) != (self.valid_count == 0):
            raise ValueError("Stage-B best-valid source is inconsistent")
        if (self.best_gate_crossing is None) != (self.pass_count == 0):
            raise ValueError("Stage-B gate-crossing source is inconsistent")
        if (self.diagnostic_top is None) != (self.valid_count > 0 or self.accepted_count == 0):
            raise ValueError("Stage-B no-valid diagnostic source is inconsistent")
        for source in (self.best_valid, self.best_gate_crossing, self.diagnostic_top):
            if source is not None and source.turn != self.turn:
                raise ValueError("Stage-B turn source belongs to another stratum")
        if self.best_valid is not None and not self.best_valid.valid_pair_search:
            raise ValueError("Stage-B best-valid source is not valid")
        if self.best_gate_crossing is not None and not self.best_gate_crossing.passes:
            raise ValueError("Stage-B crossing source does not pass")
        if self.diagnostic_top is not None and self.diagnostic_top.valid_pair_search:
            raise ValueError("Stage-B diagnostic source unexpectedly is valid")
        return self


class StageBCellRow(BaseModel):
    """One of the ten frozen Stage-B matrix cells."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: Agent
    seed: int
    run_id: str
    execution_status: CellStatus
    source_status: str | None = None
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    proposal_attempts: int = Field(ge=0)
    solver_mode_counts: dict[str, int]
    mapping_invariant_failures: int = Field(ge=0)
    turns: tuple[StageBTurnRow, ...]
    log_sha256: str | None = None
    summary_sha256: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        if self.seed not in SEEDS or self.run_id != expected_run_id(self.agent, self.seed):
            raise ValueError("Stage-B cell identity changed")
        if tuple(row.turn for row in self.turns) != TURNS:
            raise ValueError("Stage-B cell must disclose four ordered turn rows")
        if sum(row.accepted_count for row in self.turns) != self.accepted_count:
            raise ValueError("Stage-B turn quotas do not sum to accepted count")
        for turn_row in self.turns:
            for source in (
                turn_row.best_valid,
                turn_row.best_gate_crossing,
                turn_row.diagnostic_top,
            ):
                if source is not None and (
                    source.agent != self.agent
                    or source.seed != self.seed
                    or source.run_id != self.run_id
                ):
                    raise ValueError("Stage-B source belongs to another matrix cell")
        if self.execution_status == "completed":
            if (
                self.source_status != "completed"
                or self.accepted_count != EVALUATION_BUDGET
                or self.rejected_count != 0
                or self.proposal_attempts != EVALUATION_BUDGET
                or self.solver_mode_counts != {"subprocess": 2 * EVALUATION_BUDGET}
                or self.mapping_invariant_failures != 0
                or any(row.accepted_count != QUOTA_PER_TURN for row in self.turns)
                or not _is_sha256(self.log_sha256)
                or not _is_sha256(self.summary_sha256)
                or self.exception_type is not None
                or self.exception_message is not None
            ):
                raise ValueError("Stage-B completed cell violates its sole legal terminal")
        elif self.execution_status == "execution_failed":
            if not self.exception_type or not self.exception_message:
                raise ValueError("Stage-B failure lacks exception evidence")
        elif any(
            (
                self.source_status is not None,
                self.accepted_count,
                self.rejected_count,
                self.proposal_attempts,
                bool(self.solver_mode_counts),
                self.mapping_invariant_failures,
                self.log_sha256 is not None,
                self.summary_sha256 is not None,
                self.exception_type is not None,
                self.exception_message is not None,
            )
        ):
            raise ValueError("Stage-B not-run row carries execution evidence")
        return self


class TurnSeedCounts(BaseModel):
    """Seed-level gate crossing counts for one agent and turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent: Agent
    turn: int
    passing_seeds: tuple[int, ...]
    pass_count: int = Field(ge=0, le=5)


class StageBAppendix(BaseModel):
    """Strict appendix with null aggregates until all ten cells complete."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study_id: str = STUDY_ID
    spec_revision: str = SPEC_REVISION
    mapping_version: str = MAPPING_VERSION
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    study_status: Literal["complete", "study_incomplete"]
    rows: tuple[StageBCellRow, ...]
    turn_seed_counts: tuple[TurnSeedCounts, ...] | None = None
    scientific_endpoint: ScientificEndpoint | None = None
    selected_hypothesis: StageBRecordRef | None = None
    matrix_exception_type: str | None = None
    matrix_exception_message: str | None = None

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        expected = tuple((agent, seed) for agent in AGENTS for seed in SEEDS)
        actual = tuple((row.agent, row.seed) for row in self.rows)
        if actual != expected:
            raise ValueError("Stage-B rows are not in the frozen matrix order")
        complete = all(row.execution_status == "completed" for row in self.rows)
        if (self.study_status == "complete") != complete:
            raise ValueError("Stage-B study status disagrees with cell terminals")
        aggregates = (
            self.turn_seed_counts,
            self.scientific_endpoint,
            self.selected_hypothesis,
        )
        if not complete:
            if any(value is not None for value in aggregates):
                raise ValueError("incomplete Stage B cannot carry scientific aggregates")
            if not self.matrix_exception_type or not self.matrix_exception_message:
                raise ValueError("incomplete Stage B lacks matrix exception evidence")
        elif self.matrix_exception_type is not None or self.matrix_exception_message is not None:
            raise ValueError("complete Stage B cannot carry a matrix exception")
        if complete:
            if (
                self.turn_seed_counts is None
                or self.scientific_endpoint is None
                or self.selected_hypothesis is None
            ):
                raise ValueError("complete Stage B requires all scientific aggregates")
            expected_counts = tuple(
                TurnSeedCounts(
                    agent=agent,
                    turn=turn,
                    passing_seeds=tuple(
                        row.seed
                        for row in self.rows
                        if row.agent == agent
                        and row.turns[TURNS.index(turn)].pass_count > 0
                    ),
                    pass_count=sum(
                        row.agent == agent
                        and row.turns[TURNS.index(turn)].pass_count > 0
                        for row in self.rows
                    ),
                )
                for agent in AGENTS
                for turn in TURNS
            )
            if self.turn_seed_counts != expected_counts:
                raise ValueError("Stage-B seed counts do not recompute from cell rows")
            es_counts = {
                item.turn: item.pass_count
                for item in expected_counts
                if item.agent == "es"
            }
            candidates: list[StageBRecordRef] = []
            if any(count >= 4 for count in es_counts.values()):
                expected_endpoint: ScientificEndpoint = (
                    "turn_stratified_cross_seed_gate_crossing"
                )
                candidates = [
                    turn_row.best_gate_crossing
                    for row in self.rows
                    if row.agent == "es"
                    for turn_row in row.turns
                    if es_counts[turn_row.turn] >= 4
                    and turn_row.best_gate_crossing is not None
                ]
            elif any(count > 0 for count in es_counts.values()):
                expected_endpoint = "turn_stratified_seed_local_gate_crossing"
                candidates = [
                    turn_row.best_gate_crossing
                    for row in self.rows
                    if row.agent == "es"
                    for turn_row in row.turns
                    if turn_row.best_gate_crossing is not None
                ]
            else:
                expected_endpoint = (
                    "no_gate_crossing_observed_under_frozen_stratified_study"
                )
                candidates = [
                    turn_row.best_valid
                    for row in self.rows
                    if row.agent == "es"
                    for turn_row in row.turns
                    if turn_row.best_valid is not None
                ]
                if not candidates:
                    candidates = [
                        turn_row.diagnostic_top
                        for row in self.rows
                        if row.agent == "es"
                        for turn_row in row.turns
                        if turn_row.diagnostic_top is not None
                    ]
            if self.scientific_endpoint != expected_endpoint or not candidates:
                raise ValueError("Stage-B endpoint does not recompute from cell rows")
            valid_candidates = any(candidate.valid_pair_search for candidate in candidates)
            if valid_candidates:
                selected = min(
                    candidates,
                    key=lambda record: (
                        record.worst_reflected_power_fraction,
                        record.hardware_hash,
                        record.pair_hash,
                        record.turn,
                        record.seed,
                        record.step_index,
                        record.proposal_index,
                    ),
                )
            else:
                selected = min(
                    candidates,
                    key=lambda record: (
                        -record.base_score,
                        record.hardware_hash,
                        record.pair_hash,
                        record.turn,
                        record.seed,
                        record.step_index,
                        record.proposal_index,
                    ),
                )
            if self.selected_hypothesis != selected:
                raise ValueError("Stage-B selected hypothesis does not recompute")
        return self

def _valid_key(record: StageBRecordRef) -> tuple[float, str, str, int, int]:
    return (
        record.worst_reflected_power_fraction,
        record.hardware_hash,
        record.pair_hash,
        record.step_index,
        record.proposal_index,
    )


def _diagnostic_key(record: StageBRecordRef) -> tuple[float, str, str, int, int]:
    return (
        -record.base_score,
        record.hardware_hash,
        record.pair_hash,
        record.step_index,
        record.proposal_index,
    )


def summarize_turn(turn: int, records: tuple[StageBRecordRef, ...]) -> StageBTurnRow:
    """Apply the frozen within-cell ranking rules to one turn."""

    selected = tuple(record for record in records if record.turn == turn)
    groups: dict[str, list[StageBRecordRef]] = {}
    for record in selected:
        groups.setdefault(record.pair_hash, []).append(record)
    unique: list[StageBRecordRef] = []
    for group in groups.values():
        reference = group[0]
        if any(
            (
                item.hardware_hash,
                item.valid_pair_search,
                item.base_score,
                item.worst_reflected_power_fraction,
            )
            != (
                reference.hardware_hash,
                reference.valid_pair_search,
                reference.base_score,
                reference.worst_reflected_power_fraction,
            )
            for item in group[1:]
        ):
            raise ValueError("duplicate Stage-B pair hash has inconsistent diagnostics")
        unique.append(min(group, key=lambda item: (item.step_index, item.proposal_index)))
    unique_records = tuple(unique)
    valid = tuple(record for record in unique_records if record.valid_pair_search)
    passing = tuple(record for record in valid if record.passes)
    return StageBTurnRow(
        turn=turn,
        accepted_count=len(selected),
        unique_candidate_count=len(unique_records),
        valid_count=len(valid),
        pass_count=len(passing),
        best_valid=min(valid, key=_valid_key) if valid else None,
        best_gate_crossing=min(passing, key=_valid_key) if passing else None,
        diagnostic_top=(
            min(unique_records, key=_diagnostic_key)
            if unique_records and not valid
            else None
        ),
    )


def _global_key(
    record: StageBRecordRef,
) -> tuple[float, str, str, int, int, int, int]:
    return (
        record.worst_reflected_power_fraction,
        record.hardware_hash,
        record.pair_hash,
        record.turn,
        record.seed,
        record.step_index,
        record.proposal_index,
    )


def _global_diagnostic_key(
    record: StageBRecordRef,
) -> tuple[float, str, str, int, int, int, int]:
    return (
        -record.base_score,
        record.hardware_hash,
        record.pair_hash,
        record.turn,
        record.seed,
        record.step_index,
        record.proposal_index,
    )


def build_stage_b_appendix(
    rows: tuple[StageBCellRow, ...],
    records: tuple[StageBRecordRef, ...],
    *,
    matrix_exception_type: str | None = None,
    matrix_exception_message: str | None = None,
) -> StageBAppendix:
    """Build complete aggregates or an explicitly aggregate-null appendix."""

    complete = len(rows) == 10 and all(row.execution_status == "completed" for row in rows)
    if not complete:
        return StageBAppendix(
            study_status="study_incomplete",
            rows=rows,
            matrix_exception_type=matrix_exception_type or "StageBMatrixIncomplete",
            matrix_exception_message=matrix_exception_message or "matrix did not complete",
        )

    expected_record_count = len(AGENTS) * len(SEEDS) * EVALUATION_BUDGET
    identities = tuple(
        (record.run_id, record.step_index, record.proposal_index) for record in records
    )
    if len(records) != expected_record_count or len(set(identities)) != len(identities):
        raise ValueError("complete Stage B record set is incomplete or duplicated")
    for row in rows:
        cell_records = tuple(
            record
            for record in records
            if record.agent == row.agent and record.seed == row.seed
        )
        if len(cell_records) != EVALUATION_BUDGET:
            raise ValueError("complete Stage-B cell lacks 600 source records")
        if any(record.run_id != row.run_id for record in cell_records):
            raise ValueError("Stage-B record run identity changed")
        recomputed_turns = tuple(summarize_turn(turn, cell_records) for turn in TURNS)
        if recomputed_turns != row.turns:
            raise ValueError("Stage-B cell diagnostics do not recompute from records")
    counts = tuple(
        TurnSeedCounts(
            agent=agent,
            turn=turn,
            passing_seeds=tuple(
                seed
                for seed in SEEDS
                if any(
                    record.agent == agent
                    and record.seed == seed
                    and record.turn == turn
                    and record.passes
                    for record in records
                )
            ),
            pass_count=sum(
                any(
                    record.agent == agent
                    and record.seed == seed
                    and record.turn == turn
                    and record.passes
                    for record in records
                )
                for seed in SEEDS
            ),
        )
        for agent in AGENTS
        for turn in TURNS
    )
    es_counts = {item.turn: item.pass_count for item in counts if item.agent == "es"}
    if any(value >= 4 for value in es_counts.values()):
        endpoint: ScientificEndpoint = "turn_stratified_cross_seed_gate_crossing"
        pool = tuple(
            record
            for record in records
            if record.agent == "es" and record.passes and es_counts[record.turn] >= 4
        )
    elif any(value > 0 for value in es_counts.values()):
        endpoint = "turn_stratified_seed_local_gate_crossing"
        pool = tuple(record for record in records if record.agent == "es" and record.passes)
    else:
        endpoint = "no_gate_crossing_observed_under_frozen_stratified_study"
        valid_pool = tuple(
            record for record in records if record.agent == "es" and record.valid_pair_search
        )
        pool = valid_pool or tuple(record for record in records if record.agent == "es")
    if not pool:
        raise ValueError("complete Stage B has no ES records")
    selected = min(
        pool,
        key=_global_key if any(record.valid_pair_search for record in pool) else _global_diagnostic_key,
    )
    return StageBAppendix(
        study_status="complete",
        rows=rows,
        turn_seed_counts=counts,
        scientific_endpoint=endpoint,
        selected_hypothesis=selected,
    )


def render_stage_b_report(appendix: StageBAppendix) -> str:
    """Render all cells and the claim-limited exact-v2 endpoint."""

    lines = [
        "# Exact-support balanced Stage-B analysis",
        "",
        f"- Study status: `{appendix.study_status}`",
        f"- Scientific endpoint: `{appendix.scientific_endpoint}`",
        "- Verdict ceiling: `insufficient_evidence`",
        "",
        "| Agent | Seed | Status | Accepted | Unique | Valid | Passing records |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for row in appendix.rows:
        lines.append(
            f"| {row.agent} | {row.seed} | `{row.execution_status}` | "
            f"{row.accepted_count} | "
            f"{sum(turn.unique_candidate_count for turn in row.turns)} | "
            f"{sum(turn.valid_count for turn in row.turns)} | "
            f"{sum(turn.pass_count for turn in row.turns)} |"
        )
    if appendix.study_status == "study_incomplete":
        lines.extend(
            (
                "",
                f"Matrix exception: `{appendix.matrix_exception_type}` — "
                f"{appendix.matrix_exception_message}.",
                "No aggregate endpoint or selected hypothesis is reported.",
            )
        )
    else:
        lines.extend(("", "## Per-agent, per-turn seed crossings", ""))
        assert appendix.turn_seed_counts is not None
        for item in appendix.turn_seed_counts:
            seeds = ",".join(str(seed) for seed in item.passing_seeds) or "none"
            lines.append(
                f"- {item.agent}, turn {item.turn}: {item.pass_count}/5 ({seeds})."
            )
        selected = appendix.selected_hypothesis
        assert selected is not None
        lines.extend(
            (
                "",
                "## Frozen selected hypothesis",
                "",
                f"`{selected.run_id}` step {selected.step_index}, proposal "
                f"{selected.proposal_index}, turn {selected.turn}, "
                f"L={selected.worst_reflected_power_fraction:.17g}, "
                f"pair_hash=`{selected.pair_hash}`.",
            )
        )
    lines.extend(
        (
            "",
            "This is an NEC2-only descriptive endpoint. It is not independent-solver "
            "confirmation, a manufacturable antenna, or an invention claim.",
            "",
        )
    )
    return "\n".join(lines)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_stage_b_outputs(output_dir: Path, appendix: StageBAppendix) -> None:
    """Atomically write LF-only machine and human evidence."""

    appendix_bytes = (
        json.dumps(
            appendix.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    report_bytes = render_stage_b_report(appendix).encode("utf-8")
    if b"\r" in appendix_bytes or b"\r" in report_bytes:
        raise ValueError("Stage-B outputs must be LF-only")
    _atomic_write(output_dir / "appendix.json", appendix_bytes)
    _atomic_write(output_dir / "report.md", report_bytes)


def sha256_file(path: Path) -> str:
    """Return a source-addressing digest for a Stage-B artifact."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _analysis_agent(agent: StageBAgent) -> Agent:
    return "random" if agent == EXECUTION_AGENTS[0] else "es"


def _record_ref(
    record: PairedEvaluationRecord,
    agent: StageBAgent,
    seed: int,
) -> StageBRecordRef:
    evaluation = record.evaluation
    metrics = evaluation.metrics
    if (
        record.proposer != agent
        or record.proposal.proposer != agent
        or not evaluation.trajectory.valid
        or evaluation.state_a_curve.solver_mode != "subprocess"
        or evaluation.state_b_curve.solver_mode != "subprocess"
    ):
        raise ValueError("Stage-B accepted record violates frozen execution semantics")
    proposal = record.proposal
    expected_trajectory = audit_trajectory(proposal)
    expected_metrics = score_paired_curves(
        evaluation.state_a_curve,
        evaluation.state_b_curve,
    )
    if (
        evaluation.trajectory != expected_trajectory
        or evaluation.metrics != expected_metrics
        or evaluation.hardware_hash != hardware_hash(proposal.hardware)
        or evaluation.state_a_geometry_hash
        != state_geometry_hash(proposal.hardware, proposal.state_a)
        or evaluation.state_b_geometry_hash
        != state_geometry_hash(proposal.hardware, proposal.state_b)
        or evaluation.pair_hash != pair_hash(proposal)
    ):
        raise ValueError(
            "Stage-B accepted record metrics, trajectory, or hashes do not recompute"
        )
    return StageBRecordRef(
        run_id=record.run_id,
        agent=_analysis_agent(agent),
        seed=seed,
        turn=record.proposal.hardware.turn_count,
        step_index=record.step_index,
        proposal_index=record.proposal_index,
        hardware_hash=evaluation.hardware_hash,
        pair_hash=evaluation.pair_hash,
        valid_pair_search=metrics.valid_pair_search,
        base_score=metrics.base_score,
        worst_reflected_power_fraction=metrics.worst_reflected_power_fraction,
    )


def _replay_diagnostics(
    events: tuple[PairedEvaluationRecord | PairedRejectionRecord, ...],
    agent: StageBAgent,
    seed: int,
) -> StratifiedAgentDiagnostics:
    first = build_stage_b_proposer(agent, seed)
    second = build_stage_b_proposer(agent, seed)
    _replay_proposer(first, events)
    _replay_proposer(second, events)
    if first.diagnostics != second.diagnostics:
        raise ValueError("independent Stage-B evidence replays disagree")
    return first.diagnostics


def _empty_turns() -> tuple[StageBTurnRow, ...]:
    return tuple(summarize_turn(turn, ()) for turn in TURNS)


def _not_run_row(agent: StageBAgent, seed: int) -> StageBCellRow:
    analysis_agent = _analysis_agent(agent)
    return StageBCellRow(
        agent=analysis_agent,
        seed=seed,
        run_id=expected_run_id(analysis_agent, seed),
        execution_status="not_run_after_matrix_abort",
        accepted_count=0,
        rejected_count=0,
        proposal_attempts=0,
        solver_mode_counts={},
        mapping_invariant_failures=0,
        turns=_empty_turns(),
    )


def _validate_summary(
    summary: PairedRunSummary,
    config: StageBRunConfig,
    accepted_count: int,
    rejected_count: int,
) -> None:
    if (
        summary.run_id != config.run_id
        or summary.seed != config.seed
        or summary.config_hash != _config_hash(config)
        or summary.config != config.model_dump(mode="json")
        or summary.steps_completed != accepted_count
        or summary.rejected_proposals != rejected_count
        or summary.proposal_attempts != accepted_count + rejected_count
    ):
        raise ValueError("Stage-B summary does not reconstruct from its log/config")


def _load_cell(
    runs_root: Path,
    agent: StageBAgent,
    seed: int,
    inputs: StageBFrozenInputs,
) -> tuple[StageBCellRow, tuple[StageBRecordRef, ...]]:
    config = build_stage_b_config(agent, seed, inputs)
    run_directory = runs_root / config.run_id
    log_path = run_directory / "log.jsonl"
    summary_path = run_directory / "summary.json"
    if not log_path.is_file():
        raise FileNotFoundError(f"missing Stage-B log: {log_path}")
    log_bytes = log_path.read_bytes()
    events = _load_paired_events(log_path)
    replayed = _replay_diagnostics(events, agent, seed)
    state = _state_from_events(config, events)
    evaluations = tuple(
        event for event in events if isinstance(event, PairedEvaluationRecord)
    )
    rejections = tuple(
        event for event in events if isinstance(event, PairedRejectionRecord)
    )
    records = tuple(_record_ref(event, agent, seed) for event in evaluations)
    turns = tuple(summarize_turn(turn, records) for turn in TURNS)
    source_status: str | None = None
    summary_sha: str | None = None
    summary: PairedRunSummary | None = None
    if summary_path.is_file():
        summary_bytes = summary_path.read_bytes()
        summary = PairedRunSummary.model_validate_json(summary_bytes)
        source_status = summary.status
        summary_sha = hashlib.sha256(summary_bytes).hexdigest()
        source_config = StageBRunConfig.model_validate(summary.config)
        if source_config != config:
            raise ValueError("Stage-B summary config differs from the gated config")
        _validate_summary(summary, config, len(evaluations), len(rejections))
    completed = summary is not None and summary.status == "completed"
    if completed:
        assert summary is not None
        if (
            len(evaluations) != EVALUATION_BUDGET
            or rejections
            or state.evaluations_completed != EVALUATION_BUDGET
            or state.proposal_attempts != EVALUATION_BUDGET
            or state.solver_mode_counts != {"subprocess": 2 * EVALUATION_BUDGET}
            or summary.solver_mode_counts != {"subprocess": 2 * EVALUATION_BUDGET}
            or summary.termination_reason
            != "accepted paired-evaluation budget completed"
            or any(turn.accepted_count != QUOTA_PER_TURN for turn in turns)
            or replayed.accepted_count != EVALUATION_BUDGET
            or tuple(
                (island.turn_count, island.accepted_count)
                for island in replayed.islands
            )
            != ((3, 150), (4, 150), (5, 150), (6, 150))
        ):
            raise ValueError("Stage-B completed source violates its sole legal terminal")
    analysis_agent = _analysis_agent(agent)
    row = StageBCellRow(
        agent=analysis_agent,
        seed=seed,
        run_id=expected_run_id(analysis_agent, seed),
        execution_status="completed" if completed else "execution_failed",
        source_status=source_status,
        accepted_count=len(evaluations),
        rejected_count=len(rejections),
        proposal_attempts=state.proposal_attempts,
        solver_mode_counts=state.solver_mode_counts,
        mapping_invariant_failures=0,
        turns=turns,
        log_sha256=hashlib.sha256(log_bytes).hexdigest(),
        summary_sha256=summary_sha,
        exception_type=None if completed else "StageBIncompleteCell",
        exception_message=(
            None
            if completed
            else f"source terminal is {source_status or 'missing_summary'}"
        ),
    )
    return row, records


def load_stage_b_evidence(
    repo_root: Path,
    inputs: StageBFrozenInputs,
) -> StageBAppendix:
    """Load the exact matrix prefix and fail closed on the first incomplete cell."""

    rows: list[StageBCellRow] = []
    records: list[StageBRecordRef] = []
    aborted = False
    exception_type: str | None = None
    exception_message: str | None = None
    for agent, seed in MATRIX:
        if aborted:
            rows.append(_not_run_row(agent, seed))
            continue
        try:
            row, cell_records = _load_cell(
                repo_root.resolve() / "runs", agent, seed, inputs
            )
            rows.append(row)
            records.extend(cell_records)
            if row.execution_status != "completed":
                aborted = True
                exception_type = row.exception_type
                exception_message = row.exception_message
        except Exception as error:
            aborted = True
            exception_type = type(error).__name__
            exception_message = str(error) or "<no message>"
            analysis_agent = _analysis_agent(agent)
            rows.append(
                StageBCellRow(
                    agent=analysis_agent,
                    seed=seed,
                    run_id=expected_run_id(analysis_agent, seed),
                    execution_status="execution_failed",
                    accepted_count=0,
                    rejected_count=0,
                    proposal_attempts=0,
                    solver_mode_counts={},
                    mapping_invariant_failures=0,
                    turns=_empty_turns(),
                    exception_type=exception_type,
                    exception_message=exception_message,
                )
            )
    return build_stage_b_appendix(
        tuple(rows),
        tuple(records),
        matrix_exception_type=exception_type,
        matrix_exception_message=exception_message,
    )
