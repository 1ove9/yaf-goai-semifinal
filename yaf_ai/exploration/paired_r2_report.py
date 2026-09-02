"""Deterministic appendix and report for the bounded R2 study."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    audit_trajectory,
    build_state_geometry,
    hardware_hash,
    pair_hash,
    score_paired_curves,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_r2_batch import (
    R2_EVALUATION_BUDGET,
    R2_L_REQUIRED,
    R2_PARENT_PAIR_HASH,
    R2_PARENT_SOURCE_LOG_SHA256,
    R2_PARENT_SOURCE_RUN_ID,
    R2_PARENT_SOURCE_SUMMARY_SHA256,
    R2_RUN_ID_PREFIX,
    R2_SEEDS,
    SOURCE_LOG_PATH,
    SOURCE_SUMMARY_PATH,
    R2MatrixError,
    R2PairedRunConfig,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRejectionRecord,
    PairedRunSummary,
    RunStatus,
    _config_hash,
)

R2_ANALYSIS_DIRECTORY = Path(
    "artifacts/analysis/semifinal-paired-r2-robust-hunt"
)
R2_APPENDIX_PATH = R2_ANALYSIS_DIRECTORY / "appendix.json"
R2_REPORT_PATH = R2_ANALYSIS_DIRECTORY / "report.md"

R2SeedStatus = Literal[
    "completed",
    "insufficient_feasible_proposals",
    "execution_failed",
    "not_run_after_matrix_abort",
]
R2Endpoint = Literal[
    "cross_seed_gate_crossing",
    "seed_local_gate_crossing",
    "no_gate_crossing_observed_under_frozen_r2",
]
_LEGAL_TERMINALS = {"completed", "insufficient_feasible_proposals"}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


class R2RecordRef(BaseModel):
    """One source-addressed accepted R2 record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    seed: int
    step_index: int = Field(ge=0)
    proposal_index: int = Field(ge=0)
    pair_hash: str
    hardware_hash: str
    state_a_geometry_hash: str
    state_b_geometry_hash: str
    valid_pair_search: bool
    base_score: float
    search_score: float
    worst_reflected_power_fraction: float = Field(ge=0.0)


class BoundaryFieldStats(BaseModel):
    """Inclusive one-percent boundary occupancy for one integer parameter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lower_count: int = Field(ge=0)
    upper_count: int = Field(ge=0)
    either_count: int = Field(ge=0)
    fraction: float | None = Field(default=None, ge=0.0, le=1.0)


class BoundaryDiagnostics(BaseModel):
    """Six frozen continuous-coordinate boundary diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pool: Literal["valid", "accepted", "none"]
    denominator: int = Field(ge=0)
    feed_gap_ratio_ppm: BoundaryFieldStats
    terminal_ratio_ppm: BoundaryFieldStats
    state_a_total_wire_length_um: BoundaryFieldStats
    state_a_span_ratio_ppm: BoundaryFieldStats
    state_b_total_wire_length_um: BoundaryFieldStats
    state_b_span_ratio_ppm: BoundaryFieldStats

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        fields = (
            self.feed_gap_ratio_ppm,
            self.terminal_ratio_ppm,
            self.state_a_total_wire_length_um,
            self.state_a_span_ratio_ppm,
            self.state_b_total_wire_length_um,
            self.state_b_span_ratio_ppm,
        )
        for field in fields:
            if any(
                count > self.denominator
                for count in (field.lower_count, field.upper_count, field.either_count)
            ):
                raise ValueError("boundary count exceeds its disclosed denominator")
            if field.either_count != field.lower_count + field.upper_count:
                raise ValueError("boundary union count is inconsistent")
            expected_fraction = (
                None if self.denominator == 0 else field.either_count / self.denominator
            )
            if field.fraction != expected_fraction:
                raise ValueError("boundary fraction is inconsistent")
        if self.denominator == 0 and self.pool != "none":
            raise ValueError("empty boundary diagnostics must use the none pool")
        if self.denominator > 0 and self.pool == "none":
            raise ValueError("nonempty boundary diagnostics cannot use the none pool")
        return self


class TurnDistribution(BaseModel):
    """Counts over the four frozen turn-count bins."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count_3: int = Field(ge=0)
    count_4: int = Field(ge=0)
    count_5: int = Field(ge=0)
    count_6: int = Field(ge=0)
    total: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total != self.count_3 + self.count_4 + self.count_5 + self.count_6:
            raise ValueError("turn-count distribution total is inconsistent")
        return self


class R2SeedRow(BaseModel):
    """One of the five required R2 seed rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int
    run_id: str
    execution_status: R2SeedStatus
    source_run_status: RunStatus | None = None
    accepted_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    proposal_attempts: int = Field(ge=0)
    solver_mode_counts: dict[str, int]
    best_valid_l: float | None = Field(default=None, ge=0.0)
    best_valid_record: R2RecordRef | None = None
    best_gate_crossing_record: R2RecordRef | None = None
    diagnostic_top: R2RecordRef | None = None
    pass_flag: bool | None
    restart_count: int | None = Field(default=None, ge=0)
    terminal_consecutive_rejections: int | None = Field(default=None, ge=0)
    accepted_turns: TurnDistribution
    effective_turns: TurnDistribution
    rejection_reasons: dict[str, int]
    boundary: BoundaryDiagnostics
    log_sha256: str | None = None
    summary_sha256: str | None = None
    exception_type: str | None = None
    exception_message: str | None = None

    @model_validator(mode="after")
    def validate_row(self) -> Self:
        if self.seed not in R2_SEEDS or self.run_id != f"{R2_RUN_ID_PREFIX}{self.seed}":
            raise ValueError("R2 seed row identity changed")
        legal = self.execution_status in _LEGAL_TERMINALS
        if legal != (self.pass_flag is not None):
            raise ValueError("R2 seed pass flag does not match terminal status")
        if self.valid_count > self.accepted_count:
            raise ValueError("R2 valid count exceeds accepted count")
        if self.proposal_attempts != self.accepted_count + self.rejected_count:
            raise ValueError("R2 proposal-attempt count is inconsistent")
        if sum(self.rejection_reasons.values()) != self.rejected_count:
            raise ValueError("R2 rejection-reason counts are inconsistent")
        if self.accepted_turns.total != self.accepted_count:
            raise ValueError("R2 accepted turn distribution is inconsistent")
        effective = self.valid_count if self.valid_count else self.accepted_count
        if self.effective_turns.total != effective:
            raise ValueError("R2 effective turn distribution is inconsistent")
        expected_pool = "valid" if self.valid_count else (
            "accepted" if self.accepted_count else "none"
        )
        if self.boundary.pool != expected_pool or self.boundary.denominator != effective:
            raise ValueError("R2 boundary diagnostic pool is inconsistent")
        if self.valid_count:
            if self.best_valid_record is None or self.best_valid_l is None:
                raise ValueError("R2 valid pool requires its best source record")
            if (
                not self.best_valid_record.valid_pair_search
                or self.best_valid_record.run_id != self.run_id
                or self.best_valid_record.seed != self.seed
                or self.best_valid_record.worst_reflected_power_fraction
                != self.best_valid_l
            ):
                raise ValueError("R2 best-valid evidence is inconsistent")
            if self.diagnostic_top is not None:
                raise ValueError("R2 valid pool cannot carry a no-valid diagnostic top")
        elif self.best_valid_record is not None or self.best_valid_l is not None:
            raise ValueError("R2 empty valid pool cannot carry best-valid evidence")
        elif (self.diagnostic_top is None) != (self.accepted_count == 0):
            raise ValueError("R2 no-valid diagnostic top is inconsistent")
        if self.diagnostic_top is not None and (
            self.diagnostic_top.valid_pair_search
            or self.diagnostic_top.run_id != self.run_id
            or self.diagnostic_top.seed != self.seed
        ):
            raise ValueError("R2 diagnostic top is inconsistent")
        witness = self.best_gate_crossing_record
        if witness is not None and (
            not witness.valid_pair_search
            or witness.run_id != self.run_id
            or witness.seed != self.seed
            or witness.worst_reflected_power_fraction > R2_L_REQUIRED
            or witness.pair_hash == R2_PARENT_PAIR_HASH
        ):
            raise ValueError("R2 gate-crossing witness is inconsistent")
        if legal and self.pass_flag != (witness is not None):
            raise ValueError("R2 pass flag is not supported by its best valid record")
        if not legal and witness is not None:
            raise ValueError("nonterminal R2 row cannot carry a crossing witness")
        if self.execution_status == "completed" and self.accepted_count != R2_EVALUATION_BUDGET:
            raise ValueError("completed R2 row must contain 400 accepted pairs")
        if (
            self.execution_status == "insufficient_feasible_proposals"
            and self.accepted_count >= R2_EVALUATION_BUDGET
        ):
            raise ValueError("insufficient R2 row cannot exhaust the accepted budget")
        if legal:
            if self.source_run_status != self.execution_status:
                raise ValueError("R2 legal terminal lost its original runner status")
            expected_modes = (
                {} if self.accepted_count == 0 else {"subprocess": 2 * self.accepted_count}
            )
            if self.solver_mode_counts != expected_modes:
                raise ValueError("R2 terminal solver-mode counts changed")
            if (
                self.restart_count is None
                or self.terminal_consecutive_rejections is None
                or self.exception_type is not None
                or self.exception_message is not None
                or not _is_sha256(self.log_sha256)
                or not _is_sha256(self.summary_sha256)
            ):
                raise ValueError("R2 terminal diagnostics are incomplete")
            if (
                self.execution_status == "completed"
                and self.terminal_consecutive_rejections != 0
            ):
                raise ValueError("completed R2 row cannot end in a rejection")
            if (
                self.execution_status == "insufficient_feasible_proposals"
                and self.proposal_attempts < 6000
                and self.terminal_consecutive_rejections < 100
            ):
                raise ValueError("insufficient R2 row did not reach a frozen limit")
        elif self.execution_status == "execution_failed":
            if (
                self.restart_count is not None
                or self.terminal_consecutive_rejections is not None
                or not self.exception_type
                or not self.exception_message
            ):
                raise ValueError("R2 execution failure lacks exclusive exception evidence")
            if self.summary_sha256 is not None and (
                self.source_run_status is None or self.log_sha256 is None
            ):
                raise ValueError("R2 failure summary is detached from its source log")
            if self.log_sha256 is not None and not _is_sha256(self.log_sha256):
                raise ValueError("R2 failure log digest is malformed")
            if self.summary_sha256 is not None and not _is_sha256(self.summary_sha256):
                raise ValueError("R2 failure summary digest is malformed")
        else:
            if (
                self.restart_count is not None
                or self.terminal_consecutive_rejections is not None
                or self.source_run_status is not None
                or self.exception_type is not None
                or self.exception_message is not None
                or self.accepted_count
                or self.rejected_count
                or self.proposal_attempts
                or self.log_sha256 is not None
                or self.summary_sha256 is not None
                or self.solver_mode_counts
                or self.valid_count
                or self.best_valid_record is not None
                or self.best_gate_crossing_record is not None
                or self.diagnostic_top is not None
            ):
                raise ValueError("not-run R2 row carries execution evidence")
        return self


class R2BaselineDiagnostics(BaseModel):
    """Archived warm-s101 diagnostics excluded from R2 endpoint counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_run_id: Literal["semifinal-paired-es-warm-s101"]
    source_log_sha256: Literal[
        "af5b158d487577d7a07f26186ff66222b34abe05e36bd58596849dc4e3ff6c65"
    ]
    source_summary_sha256: Literal[
        "52cd3ad16c3db5b2f3d98ab2bf394e69d4f6af0381d595d88edd3de3f98e25b7"
    ]
    accepted_count: int = Field(ge=0)
    valid_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    proposal_attempts: int = Field(ge=0)
    best_valid_l: float | None = Field(default=None, ge=0.0)
    best_valid_record: R2RecordRef | None
    accepted_turns: TurnDistribution
    effective_turns: TurnDistribution
    rejection_reasons: dict[str, int]
    boundary: BoundaryDiagnostics

    @model_validator(mode="after")
    def validate_baseline(self) -> Self:
        if self.valid_count > self.accepted_count:
            raise ValueError("baseline valid count exceeds accepted count")
        if self.proposal_attempts != self.accepted_count + self.rejected_count:
            raise ValueError("baseline proposal-attempt count is inconsistent")
        if sum(self.rejection_reasons.values()) != self.rejected_count:
            raise ValueError("baseline rejection reasons are inconsistent")
        if self.accepted_turns.total != self.accepted_count:
            raise ValueError("baseline accepted turn distribution is inconsistent")
        effective = self.valid_count if self.valid_count else self.accepted_count
        if self.effective_turns.total != effective or self.boundary.denominator != effective:
            raise ValueError("baseline effective diagnostics are inconsistent")
        expected_pool = "valid" if self.valid_count else (
            "accepted" if self.accepted_count else "none"
        )
        if self.boundary.pool != expected_pool:
            raise ValueError("baseline boundary pool is inconsistent")
        if self.valid_count:
            if (
                self.best_valid_record is None
                or self.best_valid_l is None
                or not self.best_valid_record.valid_pair_search
                or self.best_valid_record.run_id != R2_PARENT_SOURCE_RUN_ID
                or self.best_valid_record.seed != 101
                or self.best_valid_record.worst_reflected_power_fraction
                != self.best_valid_l
            ):
                raise ValueError("baseline best-valid evidence is inconsistent")
        elif self.best_valid_record is not None or self.best_valid_l is not None:
            raise ValueError("baseline empty valid pool carries best-valid evidence")
        return self


class R2Appendix(BaseModel):
    """Strict five-seed appendix whose scientific aggregate is recomputable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study: Literal["robust-hunt-r2-parent-return-es"] = (
        "robust-hunt-r2-parent-return-es"
    )
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    study_status: Literal["complete", "study_incomplete"]
    rows: tuple[R2SeedRow, ...]
    baseline_diagnostics: R2BaselineDiagnostics
    matrix_exception_type: str | None = None
    matrix_exception_message: str | None = None
    pass_count: int | None = Field(default=None, ge=0, le=5)
    valid_pair_seed_count: int | None = Field(default=None, ge=0, le=5)
    cross_seed_gate_pass: bool | None = None
    scientific_endpoint: R2Endpoint | None = None

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        if tuple(row.seed for row in self.rows) != R2_SEEDS:
            raise ValueError("R2 appendix must contain the ordered five-seed matrix")
        complete = all(row.execution_status in _LEGAL_TERMINALS for row in self.rows)
        if (self.study_status == "complete") != complete:
            raise ValueError("R2 study status disagrees with seed terminals")
        if not complete:
            if any(
                value is not None
                for value in (
                    self.pass_count,
                    self.valid_pair_seed_count,
                    self.cross_seed_gate_pass,
                    self.scientific_endpoint,
                )
            ):
                raise ValueError("incomplete R2 study cannot carry scientific aggregates")
            if not self.matrix_exception_type or not self.matrix_exception_message:
                raise ValueError("incomplete R2 study lacks matrix exception evidence")
            return self
        if self.matrix_exception_type is not None or self.matrix_exception_message is not None:
            raise ValueError("complete R2 study cannot carry a matrix exception")
        pass_count = sum(row.pass_flag is True for row in self.rows)
        valid_seed_count = sum(row.valid_count > 0 for row in self.rows)
        if pass_count > valid_seed_count:
            raise ValueError("R2 passing seeds exceed seeds with valid pairs")
        cross_seed = pass_count >= 4
        endpoint: R2Endpoint
        if cross_seed:
            endpoint = "cross_seed_gate_crossing"
        elif pass_count:
            endpoint = "seed_local_gate_crossing"
        else:
            endpoint = "no_gate_crossing_observed_under_frozen_r2"
        if (
            self.pass_count != pass_count
            or self.valid_pair_seed_count != valid_seed_count
            or self.cross_seed_gate_pass != cross_seed
            or self.scientific_endpoint != endpoint
        ):
            raise ValueError("R2 scientific aggregate does not recompute from seed rows")
        return self


def _load_events(
    path: Path,
) -> tuple[tuple[PairedEvaluationRecord, ...], tuple[PairedRejectionRecord, ...]]:
    records: list[PairedEvaluationRecord] = []
    rejections: list[PairedRejectionRecord] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            payload = cast(dict[str, object], json.loads(line))
            if payload.get("event_type") == "paired_evaluation":
                records.append(PairedEvaluationRecord.model_validate(payload))
            elif payload.get("event_type") == "paired_rejection":
                rejections.append(PairedRejectionRecord.model_validate(payload))
            else:
                raise ValueError("unknown paired event type")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot parse R2 event log {path}: {error}") from error
    return tuple(records), tuple(rejections)


def _record_ref(record: PairedEvaluationRecord, seed: int) -> R2RecordRef:
    metrics = record.evaluation.metrics
    return R2RecordRef(
        run_id=record.run_id,
        seed=seed,
        step_index=record.step_index,
        proposal_index=record.proposal_index,
        pair_hash=record.evaluation.pair_hash,
        hardware_hash=record.evaluation.hardware_hash,
        state_a_geometry_hash=record.evaluation.state_a_geometry_hash,
        state_b_geometry_hash=record.evaluation.state_b_geometry_hash,
        valid_pair_search=metrics.valid_pair_search,
        base_score=metrics.base_score,
        search_score=metrics.search_score,
        worst_reflected_power_fraction=metrics.worst_reflected_power_fraction,
    )


def _best_valid(
    records: tuple[PairedEvaluationRecord, ...],
    seed: int,
) -> R2RecordRef | None:
    valid = tuple(record for record in records if record.evaluation.metrics.valid_pair_search)
    if not valid:
        return None
    selected = min(
        valid,
        key=lambda record: (
            record.evaluation.metrics.worst_reflected_power_fraction,
            record.evaluation.hardware_hash,
            record.evaluation.pair_hash,
            seed,
            record.step_index,
        ),
    )
    return _record_ref(selected, seed)


def _best_gate_crossing(
    records: tuple[PairedEvaluationRecord, ...],
    seed: int,
) -> R2RecordRef | None:
    eligible = tuple(
        record
        for record in records
        if record.evaluation.metrics.valid_pair_search
        and record.evaluation.metrics.worst_reflected_power_fraction <= R2_L_REQUIRED
        and record.evaluation.pair_hash != R2_PARENT_PAIR_HASH
    )
    if not eligible:
        return None
    selected = min(
        eligible,
        key=lambda record: (
            record.evaluation.metrics.worst_reflected_power_fraction,
            record.evaluation.hardware_hash,
            record.evaluation.pair_hash,
            seed,
            record.step_index,
        ),
    )
    return _record_ref(selected, seed)


def _diagnostic_top(
    records: tuple[PairedEvaluationRecord, ...],
    seed: int,
) -> R2RecordRef | None:
    if not records or any(record.evaluation.metrics.valid_pair_search for record in records):
        return None
    selected = min(
        records,
        key=lambda record: (
            -record.evaluation.metrics.base_score,
            record.evaluation.hardware_hash,
            record.evaluation.pair_hash,
            seed,
            record.step_index,
        ),
    )
    return _record_ref(selected, seed)


def _turn_distribution(
    records: tuple[PairedEvaluationRecord, ...],
) -> TurnDistribution:
    counts = Counter(record.proposal.hardware.turn_count for record in records)
    return TurnDistribution(
        count_3=counts[3],
        count_4=counts[4],
        count_5=counts[5],
        count_6=counts[6],
        total=len(records),
    )


def _boundary_field(
    values: tuple[int, ...],
    lower: int,
    upper: int,
) -> BoundaryFieldStats:
    span = upper - lower
    lower_count = sum(100 * (value - lower) <= span for value in values)
    upper_count = sum(100 * (upper - value) <= span for value in values)
    either_count = sum(
        100 * (value - lower) <= span or 100 * (upper - value) <= span
        for value in values
    )
    fraction = None if not values else either_count / len(values)
    return BoundaryFieldStats(
        lower_count=lower_count,
        upper_count=upper_count,
        either_count=either_count,
        fraction=fraction,
    )


def _boundary_diagnostics(
    records: tuple[PairedEvaluationRecord, ...],
) -> BoundaryDiagnostics:
    valid = tuple(record for record in records if record.evaluation.metrics.valid_pair_search)
    effective = valid if valid else records
    pool: Literal["valid", "accepted", "none"] = (
        "valid" if valid else ("accepted" if records else "none")
    )
    proposals = tuple(record.proposal for record in effective)
    return BoundaryDiagnostics(
        pool=pool,
        denominator=len(proposals),
        feed_gap_ratio_ppm=_boundary_field(
            tuple(item.hardware.feed_gap_ratio_ppm for item in proposals),
            20_000,
            60_000,
        ),
        terminal_ratio_ppm=_boundary_field(
            tuple(item.hardware.terminal_ratio_ppm for item in proposals),
            0,
            1_000_000,
        ),
        state_a_total_wire_length_um=_boundary_field(
            tuple(item.state_a.total_wire_length_um for item in proposals),
            50_000,
            100_000,
        ),
        state_a_span_ratio_ppm=_boundary_field(
            tuple(item.state_a.span_ratio_ppm for item in proposals),
            760_000,
            1_000_000,
        ),
        state_b_total_wire_length_um=_boundary_field(
            tuple(item.state_b.total_wire_length_um for item in proposals),
            22_000,
            45_000,
        ),
        state_b_span_ratio_ppm=_boundary_field(
            tuple(item.state_b.span_ratio_ppm for item in proposals),
            760_000,
            1_000_000,
        ),
    )


def _rejection_reasons(
    rejections: tuple[PairedRejectionRecord, ...],
) -> dict[str, int]:
    return dict(sorted(Counter(item.reason for item in rejections).items()))


def _seed_diagnostics(
    records: tuple[PairedEvaluationRecord, ...],
    rejections: tuple[PairedRejectionRecord, ...],
    seed: int,
) -> tuple[
    R2RecordRef | None,
    R2RecordRef | None,
    R2RecordRef | None,
    TurnDistribution,
    TurnDistribution,
    dict[str, int],
    BoundaryDiagnostics,
]:
    valid = tuple(record for record in records if record.evaluation.metrics.valid_pair_search)
    effective = valid if valid else records
    return (
        _best_valid(records, seed),
        _best_gate_crossing(records, seed),
        _diagnostic_top(records, seed),
        _turn_distribution(records),
        _turn_distribution(effective),
        _rejection_reasons(rejections),
        _boundary_diagnostics(records),
    )


def _terminal_consecutive_rejections(
    records: tuple[PairedEvaluationRecord, ...],
    rejections: tuple[PairedRejectionRecord, ...],
) -> int:
    rejected_indexes = {item.proposal_index for item in rejections}
    trailing = 0
    for proposal_index in range(len(records) + len(rejections) - 1, -1, -1):
        if proposal_index not in rejected_indexes:
            break
        trailing += 1
    return trailing


def _empty_diagnostics() -> tuple[
    TurnDistribution,
    dict[str, int],
    BoundaryDiagnostics,
]:
    empty_turns = TurnDistribution(
        count_3=0,
        count_4=0,
        count_5=0,
        count_6=0,
        total=0,
    )
    return empty_turns, {}, _boundary_diagnostics(())


def _validate_event_counts(
    run_id: str,
    records: tuple[PairedEvaluationRecord, ...],
    rejections: tuple[PairedRejectionRecord, ...],
    summary: PairedRunSummary | None,
) -> None:
    if any(record.run_id != run_id for record in records) or any(
        rejection.run_id != run_id for rejection in rejections
    ):
        raise ValueError(f"R2 log contains another run ID: {run_id}")
    if tuple(record.step_index for record in records) != tuple(range(len(records))):
        raise ValueError(f"R2 accepted steps are not contiguous: {run_id}")
    proposal_indexes = sorted(
        [record.proposal_index for record in records]
        + [rejection.proposal_index for rejection in rejections]
    )
    if proposal_indexes != list(range(len(records) + len(rejections))):
        raise ValueError(f"R2 proposal indexes are not contiguous: {run_id}")
    if summary is not None:
        expected_modes = {} if not records else {"subprocess": 2 * len(records)}
        if (
            summary.steps_completed != len(records)
            or summary.rejected_proposals != len(rejections)
            or summary.proposal_attempts != len(records) + len(rejections)
            or summary.solver_mode_counts != expected_modes
        ):
            raise ValueError(f"R2 terminal summary disagrees with its log: {run_id}")
    for record in records:
        proposal = record.proposal
        evaluation = record.evaluation
        geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
        geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
        expected = (
            hardware_hash(proposal.hardware),
            state_geometry_hash(proposal.hardware, proposal.state_a, geometry_a),
            state_geometry_hash(proposal.hardware, proposal.state_b, geometry_b),
            pair_hash(proposal),
        )
        observed = (
            evaluation.hardware_hash,
            evaluation.state_a_geometry_hash,
            evaluation.state_b_geometry_hash,
            evaluation.pair_hash,
        )
        if observed != expected:
            raise ValueError(f"R2 evaluation hashes do not reconstruct: {run_id}")
        if evaluation.trajectory != audit_trajectory(proposal):
            raise ValueError(f"R2 trajectory audit does not reconstruct: {run_id}")
        if evaluation.metrics != score_paired_curves(
            evaluation.state_a_curve,
            evaluation.state_b_curve,
        ):
            raise ValueError(f"R2 score does not reconstruct: {run_id}")
        curves = (evaluation.state_a_curve, evaluation.state_b_curve)
        if any(
            curve.solver_name != "nec2"
            or curve.solver_mode != "subprocess"
            or curve.realized_gain_dbi is not None
            for curve in curves
        ):
            raise ValueError(f"R2 log contains a non-NEC2 search curve: {run_id}")
        if (
            evaluation.state_a_curve.frequency_hz != STATE_A_FREQUENCIES_HZ
            or evaluation.state_b_curve.frequency_hz != STATE_B_FREQUENCIES_HZ
        ):
            raise ValueError(f"R2 log changed the frozen frequency table: {run_id}")


def _validated_summary_config(
    summary: PairedRunSummary,
    run_id: str,
    seed: int,
) -> R2PairedRunConfig:
    config = R2PairedRunConfig.model_validate(summary.config)
    if (
        config.run_id != run_id
        or config.seed != seed
        or summary.run_id != run_id
        or summary.seed != seed
        or summary.evaluation_budget != R2_EVALUATION_BUDGET
        or summary.verdict_ceiling != "insufficient_evidence"
        or _config_hash(config) != summary.config_hash
    ):
        raise ValueError(f"R2 summary identity or config changed: {run_id}")
    return config


def _baseline_diagnostics(repo_root: Path) -> R2BaselineDiagnostics:
    log_payload = (repo_root / SOURCE_LOG_PATH).read_bytes()
    summary_payload = (repo_root / SOURCE_SUMMARY_PATH).read_bytes()
    if (
        _sha256(log_payload) != R2_PARENT_SOURCE_LOG_SHA256
        or _sha256(summary_payload) != R2_PARENT_SOURCE_SUMMARY_SHA256
    ):
        raise ValueError("archived warm-s101 baseline bytes changed")
    records, rejections = _load_events(repo_root / SOURCE_LOG_PATH)
    summary = PairedRunSummary.model_validate_json(summary_payload)
    _validate_event_counts(R2_PARENT_SOURCE_RUN_ID, records, rejections, summary)
    best, _witness, _diagnostic, accepted_turns, effective_turns, reasons, boundary = (
        _seed_diagnostics(records, rejections, 101)
    )
    valid_count = sum(record.evaluation.metrics.valid_pair_search for record in records)
    return R2BaselineDiagnostics(
        source_run_id=R2_PARENT_SOURCE_RUN_ID,
        source_log_sha256=R2_PARENT_SOURCE_LOG_SHA256,
        source_summary_sha256=R2_PARENT_SOURCE_SUMMARY_SHA256,
        accepted_count=len(records),
        valid_count=valid_count,
        rejected_count=len(rejections),
        proposal_attempts=len(records) + len(rejections),
        best_valid_l=(
            None if best is None else best.worst_reflected_power_fraction
        ),
        best_valid_record=best,
        accepted_turns=accepted_turns,
        effective_turns=effective_turns,
        rejection_reasons=reasons,
        boundary=boundary,
    )


def _terminal_row(
    repo_root: Path,
    seed: int,
    summary: PairedRunSummary,
    restart_count: int,
) -> R2SeedRow:
    run_id = f"{R2_RUN_ID_PREFIX}{seed}"
    run_directory = repo_root / "runs" / run_id
    log_path = run_directory / "log.jsonl"
    summary_path = run_directory / "summary.json"
    _validated_summary_config(summary, run_id, seed)
    records, rejections = _load_events(log_path)
    _validate_event_counts(run_id, records, rejections, summary)
    best, witness, diagnostic, accepted_turns, effective_turns, reasons, boundary = (
        _seed_diagnostics(records, rejections, seed)
    )
    valid_count = sum(record.evaluation.metrics.valid_pair_search for record in records)
    trailing_rejections = _terminal_consecutive_rejections(records, rejections)
    expected_reason = (
        "accepted paired-evaluation budget completed"
        if summary.status == "completed"
        else "the frozen proposal-attempt limit was reached"
    )
    if summary.termination_reason != expected_reason:
        raise ValueError(f"R2 terminal reason changed: {run_id}")
    return R2SeedRow(
        seed=seed,
        run_id=run_id,
        execution_status=cast(R2SeedStatus, summary.status),
        source_run_status=summary.status,
        accepted_count=len(records),
        valid_count=valid_count,
        rejected_count=len(rejections),
        proposal_attempts=len(records) + len(rejections),
        solver_mode_counts=summary.solver_mode_counts,
        best_valid_l=(
            None if best is None else best.worst_reflected_power_fraction
        ),
        best_valid_record=best,
        best_gate_crossing_record=witness,
        diagnostic_top=diagnostic,
        pass_flag=witness is not None,
        restart_count=restart_count,
        terminal_consecutive_rejections=trailing_rejections,
        accepted_turns=accepted_turns,
        effective_turns=effective_turns,
        rejection_reasons=reasons,
        boundary=boundary,
        log_sha256=_sha256(log_path.read_bytes()),
        summary_sha256=_sha256(summary_path.read_bytes()),
    )


def _nonterminal_row(
    repo_root: Path,
    seed: int,
    status: Literal["execution_failed", "not_run_after_matrix_abort"],
    error_type: str | None,
    error_message: str | None,
) -> R2SeedRow:
    run_id = f"{R2_RUN_ID_PREFIX}{seed}"
    run_directory = repo_root / "runs" / run_id
    log_path = run_directory / "log.jsonl"
    summary_path = run_directory / "summary.json"
    source_summary = (
        PairedRunSummary.model_validate_json(summary_path.read_bytes())
        if summary_path.is_file()
        else None
    )
    if source_summary is not None:
        if not log_path.is_file():
            raise ValueError(f"R2 failure summary has no source log: {run_id}")
        _validated_summary_config(source_summary, run_id, seed)
    if status == "execution_failed" and log_path.is_file():
        records, rejections = _load_events(log_path)
        _validate_event_counts(run_id, records, rejections, source_summary)
        best, _witness, diagnostic, accepted_turns, effective_turns, reasons, boundary = (
            _seed_diagnostics(records, rejections, seed)
        )
    else:
        records = ()
        rejections = ()
        best = None
        diagnostic = None
        empty_turns, reasons, boundary = _empty_diagnostics()
        accepted_turns = empty_turns
        effective_turns = empty_turns
    return R2SeedRow(
        seed=seed,
        run_id=run_id,
        execution_status=status,
        source_run_status=(None if source_summary is None else source_summary.status),
        accepted_count=len(records),
        valid_count=sum(
            record.evaluation.metrics.valid_pair_search for record in records
        ),
        rejected_count=len(rejections),
        proposal_attempts=len(records) + len(rejections),
        solver_mode_counts=(
            {} if not records else {"subprocess": 2 * len(records)}
        ),
        best_valid_l=(
            None if best is None else best.worst_reflected_power_fraction
        ),
        best_valid_record=best,
        best_gate_crossing_record=None,
        diagnostic_top=diagnostic,
        pass_flag=None,
        restart_count=None,
        terminal_consecutive_rejections=None,
        accepted_turns=accepted_turns,
        effective_turns=effective_turns,
        rejection_reasons=reasons,
        boundary=boundary,
        log_sha256=(
            _sha256(log_path.read_bytes())
            if status == "execution_failed" and log_path.is_file()
            else None
        ),
        summary_sha256=(
            _sha256(summary_path.read_bytes())
            if status == "execution_failed" and summary_path.is_file()
            else None
        ),
        exception_type=error_type if status == "execution_failed" else None,
        exception_message=error_message if status == "execution_failed" else None,
    )


def build_r2_appendix(
    repo_root: Path,
    *,
    matrix_error: R2MatrixError | None = None,
    restart_counts: dict[int, int] | None = None,
) -> R2Appendix:
    """Build complete or diagnostic-only incomplete evidence from persisted bytes."""

    resolved = repo_root.resolve()
    known_counts = {} if restart_counts is None else dict(restart_counts)
    if matrix_error is not None:
        known_counts = {
            result.summary.seed: result.restart_count
            for result in matrix_error.confirmed_results
        }
    elif set(known_counts) != set(R2_SEEDS):
        raise ValueError(
            "complete R2 appendix requires replay counts for the exact five-seed matrix"
        )
    rows: list[R2SeedRow] = []
    for seed in R2_SEEDS:
        run_directory = resolved / "runs" / f"{R2_RUN_ID_PREFIX}{seed}"
        summary_path = run_directory / "summary.json"
        if seed in known_counts:
            if not summary_path.is_file():
                raise ValueError(f"confirmed R2 seed lacks its summary: {seed}")
            summary = PairedRunSummary.model_validate_json(summary_path.read_bytes())
            if summary.status not in _LEGAL_TERMINALS:
                raise ValueError(f"confirmed R2 seed is not a legal terminal: {seed}")
            rows.append(_terminal_row(resolved, seed, summary, known_counts[seed]))
            continue
        if matrix_error is not None and matrix_error.failed_seed == seed:
            if matrix_error.failed_seed_started:
                rows.append(
                    _nonterminal_row(
                        resolved,
                        seed,
                        "execution_failed",
                        matrix_error.cause_type,
                        matrix_error.cause_message,
                    )
                )
            else:
                if run_directory.is_dir() and any(run_directory.iterdir()):
                    raise ValueError(
                        f"unstarted R2 seed has unexpected persisted evidence: {seed}"
                    )
                rows.append(
                    _nonterminal_row(
                        resolved,
                        seed,
                        "not_run_after_matrix_abort",
                        None,
                        None,
                    )
                )
            continue
        if run_directory.is_dir() and any(run_directory.iterdir()):
            raise ValueError(
                f"R2 evidence exists outside the structured matrix prefix: {seed}"
            )
        rows.append(
            _nonterminal_row(
                resolved,
                seed,
                "not_run_after_matrix_abort",
                None,
                None,
            )
        )
    complete = all(row.execution_status in _LEGAL_TERMINALS for row in rows)
    pass_count = sum(row.pass_flag is True for row in rows) if complete else None
    valid_seed_count = sum(row.valid_count > 0 for row in rows) if complete else None
    cross_seed = None if pass_count is None else pass_count >= 4
    endpoint: R2Endpoint | None = None
    if pass_count is not None:
        endpoint = (
            "cross_seed_gate_crossing"
            if pass_count >= 4
            else "seed_local_gate_crossing"
            if pass_count >= 1
            else "no_gate_crossing_observed_under_frozen_r2"
        )
    return R2Appendix(
        study_status="complete" if complete else "study_incomplete",
        rows=tuple(rows),
        baseline_diagnostics=_baseline_diagnostics(resolved),
        matrix_exception_type=(
            None if matrix_error is None else matrix_error.cause_type
        ),
        matrix_exception_message=(
            None if matrix_error is None else matrix_error.cause_message
        ),
        pass_count=pass_count,
        valid_pair_seed_count=valid_seed_count,
        cross_seed_gate_pass=cross_seed,
        scientific_endpoint=endpoint,
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _record_text(record: R2RecordRef | None) -> str:
    if record is None:
        return "--"
    return (
        f"run={record.run_id}, step={record.step_index}, "
        f"proposal={record.proposal_index}, pair={record.pair_hash}, "
        f"hardware={record.hardware_hash}, state_a={record.state_a_geometry_hash}, "
        f"state_b={record.state_b_geometry_hash}, L="
        f"{record.worst_reflected_power_fraction:.17g}"
    )


def _turn_text(distribution: TurnDistribution) -> str:
    return (
        f"3:{distribution.count_3}, 4:{distribution.count_4}, "
        f"5:{distribution.count_5}, 6:{distribution.count_6} "
        f"(total={distribution.total})"
    )


def _reason_text(reasons: dict[str, int]) -> str:
    if not reasons:
        return "none"
    return "; ".join(f"{reason}: {reasons[reason]}" for reason in sorted(reasons))


def _boundary_rows(boundary: BoundaryDiagnostics) -> tuple[str, ...]:
    fields = (
        ("feed_gap_ratio_ppm", boundary.feed_gap_ratio_ppm),
        ("terminal_ratio_ppm", boundary.terminal_ratio_ppm),
        (
            "state_a_total_wire_length_um",
            boundary.state_a_total_wire_length_um,
        ),
        ("state_a_span_ratio_ppm", boundary.state_a_span_ratio_ppm),
        (
            "state_b_total_wire_length_um",
            boundary.state_b_total_wire_length_um,
        ),
        ("state_b_span_ratio_ppm", boundary.state_b_span_ratio_ppm),
    )
    return tuple(
        f"| `{name}` | {stats.lower_count} | {stats.upper_count} | "
        f"{stats.either_count} | "
        f"{'--' if stats.fraction is None else f'{stats.fraction:.6f}'} |"
        for name, stats in fields
    )


def render_r2_report(appendix: R2Appendix) -> str:
    """Render the human-readable report solely from the validated appendix."""

    lines = [
        "# Robust Hunt R2: bounded parent-return ES gate reproduction",
        "",
        f"**Study status:** `{appendix.study_status}`",
        "**Verdict ceiling:** `insufficient_evidence`",
    ]
    if appendix.study_status == "complete":
        lines.extend(
            (
                f"**Scientific endpoint:** `{appendix.scientific_endpoint}`",
                f"**Passing seeds:** {appendix.pass_count}/5",
                f"**Seeds with any valid pair:** {appendix.valid_pair_seed_count}/5",
            )
        )
        if appendix.pass_count == 0:
            lines.extend(
                (
                    "",
                    "No gate crossing was observed under the frozen parent, global bounds, "
                    "algorithm, budget, and five seeds. This bounded result is not a topology "
                    "or physics ceiling.",
                )
            )
        elif appendix.cross_seed_gate_pass:
            lines.extend(
                (
                    "",
                    "The endpoint is an NEC2-only, cross-seed reproducible gate-crossing "
                    "signal. It is not cross-solver confirmation.",
                )
            )
        else:
            lines.extend(
                (
                    "",
                    "At least one seed crossed the frozen NEC2 gate, but the signal was not "
                    "cross-seed reproducible under the preregistered 4/5 rule.",
                )
            )
    else:
        lines.extend(
            (
                "**Scientific endpoint:** `null`",
                f"**Matrix exception:** `{appendix.matrix_exception_type}` — "
                f"{appendix.matrix_exception_message}",
                "",
                "The matrix is incomplete. No positive or negative scientific endpoint is "
                "reported; resume is permitted only with the exact same config.",
            )
        )
    lines.extend(
        (
            "",
            "## Five-seed matrix",
            "",
            "| Seed | Status | Source status | Attempts | Accepted | Valid | Rejected | "
            "Best valid L | Pass | Restarts |",
            "|---:|---|---|---:|---:|---:|---:|---:|---|---:|",
        )
    )
    for row in appendix.rows:
        best_l = "--" if row.best_valid_l is None else f"{row.best_valid_l:.12f}"
        pass_text = "--" if row.pass_flag is None else str(row.pass_flag).lower()
        restarts = "--" if row.restart_count is None else str(row.restart_count)
        source_status = "--" if row.source_run_status is None else row.source_run_status
        lines.append(
            f"| {row.seed} | `{row.execution_status}` | `{source_status}` | "
            f"{row.proposal_attempts} | {row.accepted_count} | {row.valid_count} | "
            f"{row.rejected_count} | {best_l} | {pass_text} | {restarts} |"
        )
    lines.extend(("", "## Per-seed audit diagnostics", ""))
    for row in appendix.rows:
        short_segment_count = sum(
            count
            for reason, count in row.rejection_reasons.items()
            if "segment" in reason.lower()
        )
        lines.extend(
            (
                f"### Seed {row.seed}",
                "",
                f"- Execution/source status: `{row.execution_status}` / "
                f"`{row.source_run_status}`.",
                f"- Exception: `{row.exception_type}` — {row.exception_message}.",
                f"- Source SHA-256: log=`{row.log_sha256}`, "
                f"summary=`{row.summary_sha256}`.",
                f"- Best valid record: {_record_text(row.best_valid_record)}.",
                f"- Gate-crossing witness: "
                f"{_record_text(row.best_gate_crossing_record)}.",
                f"- No-valid diagnostic top: {_record_text(row.diagnostic_top)}.",
                f"- Accepted turn counts: {_turn_text(row.accepted_turns)}.",
                f"- Effective-pool turn counts: {_turn_text(row.effective_turns)}.",
                f"- Rejection reasons: {_reason_text(row.rejection_reasons)}.",
                f"- Short-segment rejection count: {short_segment_count}.",
                f"- Boundary pool: `{row.boundary.pool}`; "
                f"denominator={row.boundary.denominator}.",
                "",
                "| Coordinate | Lower 1% | Upper 1% | Either | Fraction |",
                "|---|---:|---:|---:|---:|",
                *_boundary_rows(row.boundary),
                "",
            )
        )
    baseline = appendix.baseline_diagnostics
    lines.extend(
        (
            "",
            "## Pre-R2 archived diagnostic",
            "",
            f"The frozen warm-s101 source contains {baseline.accepted_count} accepted pairs, "
            f"{baseline.valid_count} valid pairs, and best valid L="
            f"{baseline.best_valid_l}. It is diagnostic only and is excluded from R2 pass counts.",
            f"Accepted turn counts: {_turn_text(baseline.accepted_turns)}.",
            f"Effective turn counts: {_turn_text(baseline.effective_turns)}.",
            f"Rejection reasons: {_reason_text(baseline.rejection_reasons)}.",
            f"Best valid source: {_record_text(baseline.best_valid_record)}.",
            "",
            "| Coordinate | Lower 1% | Upper 1% | Either | Fraction |",
            "|---|---:|---:|---:|---:|",
            *_boundary_rows(baseline.boundary),
            "",
            "## Scope boundary",
            "",
            "R2 uses the unchanged NEC2 scoring instrument and does not authorize openEMS. "
            "It cannot produce `CONFIRMED`, `YAF-M1`, a manufacturable-antenna claim, or a "
            "robust physical claim. Full source rows, hashes, turn distributions, rejection "
            "counts, and six boundary diagnostics are in `appendix.json`.",
            "",
        )
    )
    return "\n".join(lines).rstrip() + "\n"


def write_r2_outputs(repo_root: Path, appendix: R2Appendix) -> None:
    """Atomically publish LF-only machine and human evidence."""

    resolved = repo_root.resolve()
    json_payload = (
        json.dumps(
            appendix.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    report_payload = render_r2_report(appendix).encode("utf-8")
    _atomic_write(resolved / R2_APPENDIX_PATH, json_payload)
    _atomic_write(resolved / R2_REPORT_PATH, report_payload)
