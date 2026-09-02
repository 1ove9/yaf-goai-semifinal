"""Cached frozen-grid NEC2 manual baseline and unique warm-parent selection."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_agents import encode_warm_parent
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    HardwareSpec,
    PairedEvaluation,
    PairedMeanderError,
    PairedProposal,
    PairedSolver,
    SearchCurve,
    StateControl,
    StateLabel,
    audit_trajectory,
    build_state_geometry,
    hardware_hash,
    iter_manual_pairs,
    manual_grid_single_state_evaluations,
    manual_hardware_grid,
    manual_state_grid,
    pair_hash,
    score_paired_curves,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRunConfig,
    PairedRunError,
    _append_jsonl,
    _canonical_bytes,
    _write_json,
)
from yaf_ai.exploration.paired_solver import PairedNEC2Solver

MANUAL_BASELINE_RUN_ID = "semifinal-paired-manual-baseline"
MANUAL_BASELINE_PREREGISTRATION_COMMIT = "52c4d38"
MANUAL_SINGLE_STATE_COUNT = 864
MANUAL_PAIR_COUNT = 5_184

CacheIdentity = tuple[str, StateLabel, int, int]


class ManualBaselineError(PairedRunError):
    """Raised when the frozen manual-baseline evidence contract is violated."""


class ManualSingleStateKey(BaseModel):
    """The unique identity of one cached single-state NEC2 sweep."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hardware_hash: str
    state_label: StateLabel
    total_wire_length_um: int
    span_ratio_ppm: int

    def identity(self) -> CacheIdentity:
        """Return the immutable tuple used by the in-memory curve cache."""

        return (
            self.hardware_hash,
            self.state_label,
            self.total_wire_length_um,
            self.span_ratio_ppm,
        )


class ManualSingleStateWorkItem(BaseModel):
    """One deterministic hardware/state row in the 864-key traversal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hardware_grid_index: int = Field(ge=0, lt=36)
    state_grid_index: int = Field(ge=0, lt=12)
    hardware: HardwareSpec
    state: StateControl
    key: ManualSingleStateKey


class ManualSingleStateEvaluationRecord(BaseModel):
    """One successful real NEC2 cache row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    event_type: Literal["single_state_evaluation"] = "single_state_evaluation"
    run_id: str = MANUAL_BASELINE_RUN_ID
    timestamp: datetime
    hardware_grid_index: int = Field(ge=0, lt=36)
    state_grid_index: int = Field(ge=0, lt=12)
    key: ManualSingleStateKey
    curve: SearchCurve


class ManualSingleStateRejectionRecord(BaseModel):
    """One geometry rejection that never calls NEC2."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    event_type: Literal["single_state_rejected"] = "single_state_rejected"
    run_id: str = MANUAL_BASELINE_RUN_ID
    timestamp: datetime
    hardware_grid_index: int = Field(ge=0, lt=36)
    state_grid_index: int = Field(ge=0, lt=12)
    key: ManualSingleStateKey
    reason: str


class ManualSingleStateResult(BaseModel):
    """Cache phase result returned to the pure pair assembly."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    cache: dict[CacheIdentity, SearchCurve]
    rejected: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    solver_mode_counts: dict[str, int]


class ManualAssemblyResult(BaseModel):
    """Pure 5,184-pair assembly result with no solver dependency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[PairedEvaluationRecord, ...]
    curve_incomplete_pairs: int = Field(ge=0)
    trajectory_invalid_pairs: int = Field(ge=0)
    scored_pairs: int = Field(ge=0)
    valid_pair_count: int = Field(ge=0)


class ManualWarmParentDocument(BaseModel):
    """The sole immutable ES-warm parent selected from the manual arm."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    parent_run_id: str
    pair_hash: str
    hardware_hash: str
    state_a_geometry_hash: str
    state_b_geometry_hash: str
    hardware_grid_index: int = Field(ge=0, lt=36)
    pair_grid_index: int = Field(ge=0, lt=MANUAL_PAIR_COUNT)
    base_score: float
    search_score: float
    valid_pair_search: bool
    positive_eligible: bool
    proposal: PairedProposal
    encoded_warm_parent: tuple[float, ...]
    baseline_commit: str | None = None

    @model_validator(mode="after")
    def validate_encoding_dimension(self) -> ManualWarmParentDocument:
        """Require exactly the preregistered seven normalized coordinates."""

        if len(self.encoded_warm_parent) != 7:
            raise ValueError("warm-parent encoding must have seven dimensions")
        return self


class ManualBaselineSummary(BaseModel):
    """Archive-compatible all-or-nothing baseline summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    result_status: Literal["completed", "execution_failed"]
    run_id: str = MANUAL_BASELINE_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = Field(ge=0, le=MANUAL_SINGLE_STATE_COUNT)
    evaluation_budget: int = MANUAL_SINGLE_STATE_COUNT
    solver_mode_counts: dict[str, int]
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    single_state_total: int = MANUAL_SINGLE_STATE_COUNT
    single_state_rejected: int = Field(ge=0, le=MANUAL_SINGLE_STATE_COUNT)
    nec2_successes: int = Field(ge=0, le=MANUAL_SINGLE_STATE_COUNT)
    pair_total: int = MANUAL_PAIR_COUNT
    curve_incomplete_pairs: int = Field(ge=0, le=MANUAL_PAIR_COUNT)
    trajectory_invalid_pairs: int = Field(ge=0, le=MANUAL_PAIR_COUNT)
    scored_pairs: int = Field(ge=0, le=MANUAL_PAIR_COUNT)
    valid_pair_count: int = Field(ge=0, le=MANUAL_PAIR_COUNT)
    warm_parent_pair_hash: str | None = None
    warm_parent_sha256: str | None = None
    failure_message: str | None = None


def iter_manual_single_state_work() -> tuple[ManualSingleStateWorkItem, ...]:
    """Return all 864 keys in the frozen hardware, A, then B order."""

    rows: list[ManualSingleStateWorkItem] = []
    for hardware_index, hardware in enumerate(manual_hardware_grid()):
        digest = hardware_hash(hardware)
        for state_label in ("A", "B"):
            for state_index, state in enumerate(manual_state_grid(state_label)):
                rows.append(
                    ManualSingleStateWorkItem(
                        hardware_grid_index=hardware_index,
                        state_grid_index=state_index,
                        hardware=hardware,
                        state=state,
                        key=ManualSingleStateKey(
                            hardware_hash=digest,
                            state_label=state_label,
                            total_wire_length_um=state.total_wire_length_um,
                            span_ratio_ppm=state.span_ratio_ppm,
                        ),
                    )
                )
    if len(rows) != MANUAL_SINGLE_STATE_COUNT:
        raise ManualBaselineError("manual single-state traversal is not exactly 864 rows")
    identities = {row.key.identity() for row in rows}
    if len(identities) != MANUAL_SINGLE_STATE_COUNT:
        raise ManualBaselineError("manual single-state traversal contains duplicate keys")
    return tuple(rows)


def _frequencies(state: StateLabel) -> tuple[float, ...]:
    return STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ


async def execute_manual_single_states(
    *,
    solver: PairedSolver,
    log_path: Path,
    work_items: Iterable[ManualSingleStateWorkItem] | None = None,
) -> ManualSingleStateResult:
    """Build and solve every unique valid key once, logging rejections for free."""

    rows = iter_manual_single_state_work() if work_items is None else tuple(work_items)
    cache: dict[CacheIdentity, SearchCurve] = {}
    rejected = 0
    succeeded = 0
    for row in rows:
        identity = row.key.identity()
        if identity in cache:
            raise ManualBaselineError("single-state key would be solved twice")
        try:
            geometry = build_state_geometry(row.hardware, row.state)
        except (PairedMeanderError, ValueError) as error:
            rejection_record = ManualSingleStateRejectionRecord(
                timestamp=datetime.now(UTC),
                hardware_grid_index=row.hardware_grid_index,
                state_grid_index=row.state_grid_index,
                key=row.key,
                reason=f"{type(error).__name__}: {error}",
            )
            _append_jsonl(
                log_path, rejection_record.model_dump(mode="json")
            )
            rejected += 1
            continue
        curve = await solver(geometry, row.state.state, _frequencies(row.state.state))
        if curve.solver_name != "nec2" or curve.solver_mode != "subprocess":
            raise ManualBaselineError("manual baseline requires real NEC2 subprocess curves")
        if curve.realized_gain_dbi is not None:
            raise ManualBaselineError("manual baseline search curves must not contain gain")
        evaluation_record = ManualSingleStateEvaluationRecord(
            timestamp=datetime.now(UTC),
            hardware_grid_index=row.hardware_grid_index,
            state_grid_index=row.state_grid_index,
            key=row.key,
            curve=curve,
        )
        _append_jsonl(log_path, evaluation_record.model_dump(mode="json"))
        cache[identity] = curve
        succeeded += 1
    return ManualSingleStateResult(
        cache=cache,
        rejected=rejected,
        succeeded=succeeded,
        solver_mode_counts={} if succeeded == 0 else {"subprocess": succeeded},
    )


def _cache_identity(hardware: HardwareSpec, state: StateControl) -> CacheIdentity:
    return (
        hardware_hash(hardware),
        state.state,
        state.total_wire_length_um,
        state.span_ratio_ppm,
    )


def assemble_manual_records(
    cache: Mapping[CacheIdentity, SearchCurve],
    pairs: Iterable[tuple[int, int, PairedProposal]] | None = None,
) -> ManualAssemblyResult:
    """Assemble cached A/B curves and audit trajectories without a solver call."""

    source = iter_manual_pairs() if pairs is None else pairs
    records: list[PairedEvaluationRecord] = []
    curve_incomplete = 0
    trajectory_invalid = 0
    valid_pair_count = 0
    for hardware_index, pair_index, proposal in source:
        curve_a = cache.get(_cache_identity(proposal.hardware, proposal.state_a))
        curve_b = cache.get(_cache_identity(proposal.hardware, proposal.state_b))
        if curve_a is None or curve_b is None:
            curve_incomplete += 1
            continue
        metrics = score_paired_curves(curve_a, curve_b)
        trajectory = audit_trajectory(proposal)
        if not trajectory.valid:
            trajectory_invalid += 1
            continue
        geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
        geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
        evaluation = PairedEvaluation(
            hardware_hash=hardware_hash(proposal.hardware),
            state_a_geometry_hash=state_geometry_hash(
                proposal.hardware, proposal.state_a, geometry_a
            ),
            state_b_geometry_hash=state_geometry_hash(
                proposal.hardware, proposal.state_b, geometry_b
            ),
            pair_hash=pair_hash(proposal),
            metrics=metrics,
            trajectory=trajectory,
            state_a_curve=curve_a,
            state_b_curve=curve_b,
        )
        records.append(
            PairedEvaluationRecord(
                run_id=MANUAL_BASELINE_RUN_ID,
                step_index=len(records),
                proposal_index=pair_index,
                timestamp=datetime.now(UTC),
                proposer="manual-physics-baseline",
                proposal=proposal,
                evaluation=evaluation,
                hardware_grid_index=hardware_index,
                pair_grid_index=pair_index,
            )
        )
        if metrics.valid_pair_search:
            valid_pair_count += 1
    return ManualAssemblyResult(
        records=tuple(records),
        curve_incomplete_pairs=curve_incomplete,
        trajectory_invalid_pairs=trajectory_invalid,
        scored_pairs=len(records),
        valid_pair_count=valid_pair_count,
    )


def freeze_manual_warm_parent(
    records: Iterable[PairedEvaluationRecord],
) -> ManualWarmParentDocument:
    """Freeze exactly one parent using the preregistered manual-only ordering."""

    pool = [
        record
        for record in records
        if record.evaluation.trajectory.valid
        and record.hardware_grid_index is not None
        and record.pair_grid_index is not None
    ]
    if not pool:
        raise ManualBaselineError("manual warm-parent pool is empty")
    valid = [record for record in pool if record.evaluation.metrics.valid_pair_search]
    positive_eligible = bool(valid)
    ranking_pool = valid if valid else pool
    selected = min(
        ranking_pool,
        key=lambda record: (
            -record.evaluation.metrics.base_score,
            record.evaluation.hardware_hash,
            record.hardware_grid_index,
            record.pair_grid_index,
        ),
    )
    if selected.hardware_grid_index is None or selected.pair_grid_index is None:
        raise ManualBaselineError("selected manual row lacks frozen grid indexes")
    evaluation = selected.evaluation
    encoded = encode_warm_parent(selected.proposal)
    return ManualWarmParentDocument(
        parent_run_id=selected.run_id,
        pair_hash=evaluation.pair_hash,
        hardware_hash=evaluation.hardware_hash,
        state_a_geometry_hash=evaluation.state_a_geometry_hash,
        state_b_geometry_hash=evaluation.state_b_geometry_hash,
        hardware_grid_index=selected.hardware_grid_index,
        pair_grid_index=selected.pair_grid_index,
        base_score=evaluation.metrics.base_score,
        search_score=evaluation.metrics.search_score,
        valid_pair_search=evaluation.metrics.valid_pair_search,
        positive_eligible=positive_eligible,
        proposal=selected.proposal,
        encoded_warm_parent=tuple(float(value) for value in encoded),
    )


def _baseline_config() -> tuple[dict[str, Any], str]:
    paired = PairedRunConfig(
        run_id=MANUAL_BASELINE_RUN_ID,
        agent="manual",
        seed=0,
        evaluation_budget=MANUAL_SINGLE_STATE_COUNT,
        anchor_released=False,
        openems_cross_check_authorized=False,
        preregistration_commit=MANUAL_BASELINE_PREREGISTRATION_COMMIT,
    )
    config: dict[str, Any] = {
        **paired.model_dump(mode="json"),
        "single_state_key_order": "hardware; A grid; B grid",
        "single_state_count": MANUAL_SINGLE_STATE_COUNT,
        "pair_count": MANUAL_PAIR_COUNT,
        "assembly": "cached 12x12 per hardware; no solver",
        "warm_parent_order": (
            "valid eligibility; base_score desc; hardware_hash; "
            "hardware_grid_index; pair_grid_index"
        ),
    }
    return config, hashlib.sha256(_canonical_bytes(config)).hexdigest()


def _summary(
    *,
    result_status: Literal["completed", "execution_failed"],
    started_at: datetime,
    config: dict[str, Any],
    config_hash: str,
    single: ManualSingleStateResult | None,
    assembly: ManualAssemblyResult | None,
    parent: ManualWarmParentDocument | None,
    parent_sha256: str | None,
    failure_message: str | None,
) -> ManualBaselineSummary:
    succeeded = 0 if single is None else single.succeeded
    rejected = 0 if single is None else single.rejected
    modes = {} if single is None else single.solver_mode_counts
    return ManualBaselineSummary(
        result_status=result_status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=config_hash,
        config=config,
        steps_completed=succeeded,
        solver_mode_counts=modes,
        single_state_rejected=rejected,
        nec2_successes=succeeded,
        curve_incomplete_pairs=(0 if assembly is None else assembly.curve_incomplete_pairs),
        trajectory_invalid_pairs=(
            0 if assembly is None else assembly.trajectory_invalid_pairs
        ),
        scored_pairs=0 if assembly is None else assembly.scored_pairs,
        valid_pair_count=0 if assembly is None else assembly.valid_pair_count,
        warm_parent_pair_hash=None if parent is None else parent.pair_hash,
        warm_parent_sha256=parent_sha256,
        failure_message=failure_message,
    )


async def run_manual_baseline(
    repo_root: Path,
    solver: PairedSolver | None = None,
) -> ManualBaselineSummary:
    """Execute only the preregistered cached manual baseline and freeze its parent."""

    if manual_grid_single_state_evaluations() != MANUAL_SINGLE_STATE_COUNT:
        raise ManualBaselineError("frozen manual grid no longer contains 864 states")
    run_directory = repo_root / "runs" / MANUAL_BASELINE_RUN_ID
    run_directory.mkdir(parents=True, exist_ok=False)
    log_path = run_directory / "log.jsonl"
    log_path.touch()
    summary_path = run_directory / "summary.json"
    warm_parent_path = (
        repo_root
        / "artifacts"
        / "analysis"
        / "semifinal-paired-manual-baseline"
        / "warm_parent.json"
    )
    started_at = datetime.now(UTC)
    config, config_hash = _baseline_config()
    paired_solver: PairedSolver = PairedNEC2Solver() if solver is None else solver
    single: ManualSingleStateResult | None = None
    assembly: ManualAssemblyResult | None = None
    parent: ManualWarmParentDocument | None = None
    try:
        single = await execute_manual_single_states(
            solver=paired_solver,
            log_path=log_path,
        )
        assembly = assemble_manual_records(single.cache)
        for record in assembly.records:
            _append_jsonl(log_path, record.model_dump(mode="json"))
        parent = freeze_manual_warm_parent(assembly.records)
        parent_payload = parent.model_dump(mode="json")
        _write_json(warm_parent_path, parent_payload)
        parent_sha256 = hashlib.sha256(warm_parent_path.read_bytes()).hexdigest()
        summary = _summary(
            result_status="completed",
            started_at=started_at,
            config=config,
            config_hash=config_hash,
            single=single,
            assembly=assembly,
            parent=parent,
            parent_sha256=parent_sha256,
            failure_message=None,
        )
    except Exception as error:
        summary = _summary(
            result_status="execution_failed",
            started_at=started_at,
            config=config,
            config_hash=config_hash,
            single=single,
            assembly=assembly,
            parent=None,
            parent_sha256=None,
            failure_message=f"{type(error).__name__}: {error}",
        )
    _write_json(summary_path, summary.model_dump(mode="json"))
    return summary
