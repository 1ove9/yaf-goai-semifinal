"""Recoverable sequential batch execution for exploration experiments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yaf_ai.exploration.baselines import (
    ClassicTemplateBaseline,
    ExplorationAgent,
    GPExplorationAgent,
    RandomSearchBaseline,
)
from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    DiscoveryPolicy,
    ExplorationConfig,
)
from yaf_ai.exploration.logger import (
    AuditStepRecord,
    ExplorationLogger,
    RunSummary,
    config_hash,
)
from yaf_ai.exploration.pixel import (
    WIFI24_PIXEL_PROPOSAL_SPACE,
    PixelProposalSpace,
)
from yaf_ai.exploration.pixel_agents import EvolvePixelAgent, RandomPixelBaseline
from yaf_ai.exploration.proposal_space import (
    MEANDER_PROPOSAL_SPACE,
    MEANDER_PROPOSAL_SPACE_V2,
    MEANDER_PROPOSAL_SPACE_V21,
    PATCH_PROPOSAL_SPACE,
    ProposalSpace,
)
from yaf_ai.exploration.specs import SPEC_NAMES, ExplorationSpec, get_spec
from yaf_ai.exploration.wire import wire_spec_updates

AgentName = Literal[
    "gp",
    "random",
    "classic",
    "evolve_pixel",
    "random_pixel",
    "preflight_pixel",
    "es",
]
RunStatus = Literal["running", "completed", "failed"]
RunExecutor = Callable[["BatchRunRecord", Path], Awaitable["RunExecution"]]
CompletionHook = Callable[["BatchRunRecord"], None]
BudgetChoice = tuple[int, tuple[int, ...]]

DEFAULT_DURATION_LIMIT_SECONDS = 2.5 * 60.0 * 60.0
DEFAULT_BUDGET_CHOICES: tuple[BudgetChoice, ...] = (
    (20, (101, 202, 303, 404, 505)),
    (20, (101, 202, 303)),
    (16, (101, 202, 303)),
)
DEFAULT_PIXEL_DURATION_LIMIT_SECONDS = 60.0 * 60.0
DEFAULT_PIXEL_BUDGET_CHOICES: tuple[BudgetChoice, ...] = (
    (40, (101, 202, 303)),
    (32, (101, 202, 303)),
    (24, (101, 202, 303)),
    (16, (101, 202, 303)),
)
DEFAULT_WIRE_DURATION_LIMIT_SECONDS = 1.5 * 60.0 * 60.0
DEFAULT_WIRE_BUDGET_CHOICES: tuple[BudgetChoice, ...] = (
    (40, (101, 202, 303, 404, 505)),
    (40, (101, 202, 303)),
    (32, (101, 202, 303)),
)
DAY5_WIRE_BUDGET_CHOICES: tuple[BudgetChoice, ...] = (
    (400, (101, 202, 303, 404, 505)),
)
DAY45_WIRE_STEADY_STATE_SECONDS_PER_EVALUATION = 109.345 / 401.0
BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class BatchError(RuntimeError):
    """Raised when a batch cannot continue reproducibly."""


class BatchRunRecord(BaseModel):
    """Durable status for one deterministic matrix cell."""

    model_config = ConfigDict(frozen=True)

    run_key: str
    run_id: str
    spec_name: str
    agent: AgentName
    seed: int
    budget: int = Field(gt=0)
    status: RunStatus
    duration_seconds: float | None = Field(default=None, ge=0.0)
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class RunExecution(BaseModel):
    """Successful result returned by a run executor."""

    model_config = ConfigDict(frozen=True)

    duration_seconds: float = Field(ge=0.0)
    steps_completed: int = Field(ge=0)


class BatchState(BaseModel):
    """Crash-safe batch progress state."""

    model_config = ConfigDict(frozen=True)

    batch_id: str
    config_hash: str | None = None
    runs: tuple[BatchRunRecord, ...] = ()


class ReferenceScore(BaseModel):
    """Frozen score imported from an earlier source-addressed run."""

    model_config = ConfigDict(frozen=True)

    label: str
    score: float
    source_run_id: str


class BatchConfig(BaseModel):
    """Fully frozen scientific choices made before the comparison matrix."""

    model_config = ConfigDict(frozen=True)

    batch_id: str
    specs: dict[str, ExplorationSpec]
    solver: Literal["openems", "nec2"] = "openems"
    budget: int = Field(gt=0)
    seeds: tuple[int, ...]
    proposal_space: ProposalSpace | PixelProposalSpace
    discovery_policy: DiscoveryPolicy
    calibration_seconds: dict[str, float]
    duration_limit_seconds: float
    estimated_total_seconds: float
    selection_reason: str
    experiment_kind: Literal["parametric", "pixel", "wire"] = "parametric"
    reference_scores: tuple[ReferenceScore, ...] = ()


class BatchConfigDocument(BaseModel):
    """Self-hashed on-disk batch configuration."""

    model_config = ConfigDict(frozen=True)

    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: BatchConfig


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def batch_config_hash(config: BatchConfig) -> str:
    """Return the canonical SHA-256 for a frozen batch configuration."""

    canonical = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_state(path: Path, state: BatchState) -> None:
    _write_json(path, state.model_dump(mode="json"))


def _load_state(path: Path, batch_id: str) -> BatchState:
    if not path.is_file():
        return BatchState(batch_id=batch_id)
    try:
        state = BatchState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise BatchError(f"invalid batch state: {error}") from error
    if state.batch_id != batch_id:
        raise BatchError(
            f"state batch_id {state.batch_id!r} does not match {batch_id!r}"
        )
    keys = [record.run_key for record in state.runs]
    if len(keys) != len(set(keys)):
        raise BatchError("batch state contains duplicate run keys")
    return state


def _write_config(path: Path, config: BatchConfig) -> BatchConfigDocument:
    document = BatchConfigDocument(config_hash=batch_config_hash(config), config=config)
    _write_json(path, document.model_dump(mode="json"))
    return document


def load_batch_config(path: Path) -> BatchConfigDocument:
    """Load and verify a self-hashed batch configuration."""

    try:
        document = BatchConfigDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise BatchError(f"invalid batch config: {error}") from error
    actual = batch_config_hash(document.config)
    if actual != document.config_hash:
        raise BatchError(
            f"batch config hash mismatch: expected={document.config_hash} actual={actual}"
        )
    return document


def estimate_duration_seconds(
    calibration_seconds: dict[str, float],
    *,
    budget: int,
    seeds: Sequence[int],
) -> float:
    """Estimate classic calibration plus the paired GP/random matrix duration."""

    evaluations_per_spec = 1 + 2 * len(seeds) * budget
    return sum(calibration_seconds.values()) * evaluations_per_spec


def choose_experiment_shape(
    calibration_seconds: dict[str, float],
    *,
    duration_limit_seconds: float = DEFAULT_DURATION_LIMIT_SECONDS,
    choices: Sequence[BudgetChoice] = DEFAULT_BUDGET_CHOICES,
) -> tuple[int, tuple[int, ...], float, str]:
    """Choose the highest-priority matrix that fits the fixed duration limit."""

    for budget, seeds in choices:
        estimate = estimate_duration_seconds(
            calibration_seconds,
            budget=budget,
            seeds=seeds,
        )
        if estimate <= duration_limit_seconds:
            reason = (
                f"Selected budget={budget} with {len(seeds)} seeds because the "
                f"calibrated estimate {estimate:.1f}s fits the "
                f"{duration_limit_seconds:.1f}s limit."
            )
            return budget, seeds, estimate, reason
    raise BatchError(
        "no permitted budget/seed matrix fits the calibrated 2.5-hour limit"
    )


def _run_key(spec_name: str, agent: AgentName, seed: int) -> str:
    return f"{spec_name}:{agent}:{seed}"


def _run_id(batch_id: str, spec_name: str, agent: AgentName, seed: int) -> str:
    return f"{batch_id}-{spec_name}-{agent}-s{seed}"


def _find_record(state: BatchState, run_key: str) -> BatchRunRecord | None:
    return next((record for record in state.runs if record.run_key == run_key), None)


def _replace_record(state: BatchState, replacement: BatchRunRecord) -> BatchState:
    records = list(state.runs)
    existing = next(
        (
            index
            for index, record in enumerate(records)
            if record.run_key == replacement.run_key
        ),
        None,
    )
    if existing is None:
        records.append(replacement)
    else:
        records[existing] = replacement
    return state.model_copy(update={"runs": tuple(records)})


def _build_agent(
    record: BatchRunRecord,
    config: ExplorationConfig,
) -> ExplorationAgent:
    if record.agent == "gp":
        return GPExplorationAgent(config)
    if record.agent == "random":
        return RandomSearchBaseline(config)
    if record.agent == "evolve_pixel":
        return EvolvePixelAgent(config)
    if record.agent in {"random_pixel", "preflight_pixel"}:
        return RandomPixelBaseline(config)
    return ClassicTemplateBaseline(config)


async def execute_experiment_run(
    record: BatchRunRecord,
    runs_root: Path,
) -> RunExecution:
    """Execute one real openEMS matrix cell with its deterministic run id."""

    pixel_agent = record.agent in {
        "evolve_pixel",
        "random_pixel",
        "preflight_pixel",
    }
    config = ExplorationConfig(
        spec=get_spec(record.spec_name),
        evaluation_budget=record.budget,
        seed=record.seed,
        solver="openems",
        proposal_space_version=(
            WIFI24_PIXEL_PROPOSAL_SPACE.version
            if pixel_agent
            else PATCH_PROPOSAL_SPACE.version
        ),
    )
    audit_logger = ExplorationLogger(
        config=config,
        runs_root=runs_root,
        run_id=record.run_id,
    )
    environment = AntennaExplorationEnv(config, audit_logger=audit_logger)
    environment.reset()
    agent = _build_agent(record, config)
    started = time.perf_counter()
    results = await agent.run(environment)
    environment.finish()
    return RunExecution(
        duration_seconds=time.perf_counter() - started,
        steps_completed=len(results),
    )


def _wire_exploration_config(record: BatchRunRecord) -> ExplorationConfig:
    wire_spec = get_spec(record.spec_name).model_copy(update=wire_spec_updates())
    day5 = record.run_id.startswith("day5-wire-v6")
    proposal_space = (
        MEANDER_PROPOSAL_SPACE_V21
        if record.run_id.startswith("day5-wire-v6r2-")
        else MEANDER_PROPOSAL_SPACE_V2
        if day5
        else MEANDER_PROPOSAL_SPACE
    )
    return ExplorationConfig(
        spec=wire_spec,
        evaluation_budget=record.budget,
        seed=record.seed,
        solver="nec2",
        proposal_space_version=proposal_space.version,
        fixed_problem_definition=(
            "The wifi24 band, 30x30 mm box, wire radius, minimum pitch, NEC2 "
            "oracle, adaptive lambda/20 segmentation, wire-realized-gain-v2 score "
            "with zero lossless-efficiency weight, budget, and discovery policy "
            "are fixed."
        ),
        explorable_problem_definition=(
            "The agent may explore the shared five-dimensional symmetric planar "
            f"meander-dipole centerline space {proposal_space.version}."
        ),
    )


async def execute_wire_experiment_run(
    record: BatchRunRecord,
    runs_root: Path,
) -> RunExecution:
    """Execute one real NEC2 meander or box-straight reference run."""

    config = _wire_exploration_config(record)
    audit_logger = ExplorationLogger(
        config=config,
        runs_root=runs_root,
        run_id=record.run_id,
    )
    environment = AntennaExplorationEnv(config, audit_logger=audit_logger)
    environment.reset()
    agent = _build_agent(record, config)
    started = time.perf_counter()
    try:
        results = await agent.run(environment)
    except Exception as error:
        audit_logger.write_failure_summary(
            f"{type(error).__name__}: {error}", environment.results
        )
        raise
    environment.finish()
    return RunExecution(
        duration_seconds=time.perf_counter() - started,
        steps_completed=len(results),
    )


def materialize_failed_wire_evidence(state: BatchState, runs_root: Path) -> None:
    """Seal legacy failed cells that predate automatic failure summaries."""

    for record in state.runs:
        if record.status != "failed":
            continue
        directory = runs_root / record.run_id
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / "log.jsonl"
        summary_path = directory / "summary.json"
        if summary_path.is_file():
            continue
        if not log_path.is_file():
            log_path.write_bytes(b"")
        evaluations: list[AuditStepRecord] = []
        rejected = 0
        for line in log_path.read_text(encoding="utf-8").splitlines():
            raw = json.loads(line)
            if raw.get("event_type") == "evaluation":
                evaluations.append(AuditStepRecord.model_validate(raw))
            elif raw.get("event_type") == "rejected":
                rejected += 1
        config = _wire_exploration_config(record)
        modes: dict[str, int] = {}
        for evaluation in evaluations:
            modes[evaluation.solver_mode] = modes.get(evaluation.solver_mode, 0) + 1
        summary = RunSummary(
            run_id=record.run_id,
            started_at=record.started_at,
            finished_at=record.finished_at or datetime.now(UTC),
            seed=record.seed,
            config_hash=config_hash(config),
            config=config.model_dump(mode="json"),
            steps_completed=len(evaluations),
            evaluation_budget=record.budget,
            solver_mode_counts=modes,
            top_designs=sorted(
                evaluations, key=lambda item: item.score, reverse=True
            )[:3],
            rejected_proposals=rejected,
            status="failed",
            failure=record.error or "unknown batch failure",
        )
        _write_json(summary_path, summary.model_dump(mode="json"))


def seal_interrupted_wire_batch(
    batch_id: str,
    *,
    repo_root: Path,
    reason: str,
) -> BatchState:
    """Mark only currently running wire cells failed and seal partial evidence."""

    state_path = repo_root / "runs" / f"batch_{batch_id}" / "state.json"
    state = _load_state(state_path, batch_id)
    updated = state
    for record in state.runs:
        if record.status != "running":
            continue
        failed = record.model_copy(
            update={
                "status": "failed",
                "error": reason,
                "finished_at": datetime.now(UTC),
            }
        )
        updated = _replace_record(updated, failed)
    _write_state(state_path, updated)
    materialize_failed_wire_evidence(updated, repo_root / "runs")
    return updated


async def _run_record(
    state: BatchState,
    *,
    state_path: Path,
    runs_root: Path,
    batch_id: str,
    spec_name: str,
    agent: AgentName,
    seed: int,
    budget: int,
    executor: RunExecutor,
    on_completed: CompletionHook | None,
) -> BatchState:
    key = _run_key(spec_name, agent, seed)
    existing = _find_record(state, key)
    if existing is not None and existing.status in {"completed", "failed"}:
        if existing.status == "completed" and on_completed is not None:
            on_completed(existing)
        print(f"SKIP {existing.run_id} status={existing.status}", flush=True)
        return state
    if existing is not None and existing.status == "running":
        interrupted = existing.model_copy(
            update={
                "status": "failed",
                "error": "interrupted before a complete summary was recorded",
                "finished_at": datetime.now(UTC),
            }
        )
        state = _replace_record(state, interrupted)
        _write_state(state_path, state)
        print(f"FAIL {interrupted.run_id} error={interrupted.error}", flush=True)
        return state

    started_at = datetime.now(UTC)
    running = BatchRunRecord(
        run_key=key,
        run_id=_run_id(batch_id, spec_name, agent, seed),
        spec_name=spec_name,
        agent=agent,
        seed=seed,
        budget=budget,
        status="running",
        started_at=started_at,
    )
    state = _replace_record(state, running)
    _write_state(state_path, state)
    print(
        f"START {running.run_id} spec={spec_name} agent={agent} "
        f"seed={seed} budget={budget}",
        flush=True,
    )
    try:
        execution = await executor(running, runs_root)
    except Exception as error:
        failed = running.model_copy(
            update={
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
                "finished_at": datetime.now(UTC),
            }
        )
        state = _replace_record(state, failed)
        _write_state(state_path, state)
        print(f"FAIL {failed.run_id} error={failed.error}", flush=True)
        if on_completed is not None:
            on_completed(failed)
        return state

    completed = running.model_copy(
        update={
            "status": "completed",
            "duration_seconds": execution.duration_seconds,
            "finished_at": datetime.now(UTC),
        }
    )
    state = _replace_record(state, completed)
    _write_state(state_path, state)
    print(
        f"DONE {completed.run_id} steps={execution.steps_completed} "
        f"seconds={execution.duration_seconds:.3f}",
        flush=True,
    )
    if on_completed is not None:
        on_completed(completed)
    return state


def _calibration_seconds(
    state: BatchState,
    spec_names: Sequence[str],
) -> dict[str, float]:
    completed = {
        record.spec_name: record.duration_seconds
        for record in state.runs
        if record.agent == "classic"
        and record.status == "completed"
        and record.duration_seconds is not None
    }
    successful = [duration for duration in completed.values() if duration is not None]
    fallback = max(successful, default=11.0)
    return {
        spec_name: float(completed.get(spec_name) or fallback)
        for spec_name in spec_names
    }


def choose_pixel_experiment_shape(
    calibration_seconds: float,
    *,
    duration_limit_seconds: float = DEFAULT_PIXEL_DURATION_LIMIT_SECONDS,
    choices: Sequence[BudgetChoice] = DEFAULT_PIXEL_BUDGET_CHOICES,
) -> tuple[int, tuple[int, ...], float, str]:
    """Choose the largest frozen pixel matrix that fits the one-hour limit."""

    for budget, seeds in choices:
        estimate = calibration_seconds * (1 + 2 * len(seeds) * budget)
        if estimate <= duration_limit_seconds:
            reason = (
                f"Selected pixel budget={budget} with {len(seeds)} seeds because "
                f"the measured {calibration_seconds:.3f}s/evaluation implies "
                f"{estimate:.1f}s, within the {duration_limit_seconds:.1f}s limit."
            )
            return budget, seeds, estimate, reason
    raise BatchError("no permitted pixel budget fits the calibrated one-hour limit")


async def run_batch(
    batch_id: str,
    *,
    repo_root: Path,
    executor: RunExecutor = execute_experiment_run,
    spec_names: Sequence[str] = SPEC_NAMES,
    duration_limit_seconds: float = DEFAULT_DURATION_LIMIT_SECONDS,
    choices: Sequence[BudgetChoice] = DEFAULT_BUDGET_CHOICES,
    on_completed: CompletionHook | None = None,
) -> BatchState:
    """Calibrate, freeze, and execute one sequential recoverable batch."""

    if not BATCH_ID_PATTERN.fullmatch(batch_id) or batch_id in {".", ".."}:
        raise BatchError(f"invalid batch id: {batch_id!r}")
    unknown = sorted(set(spec_names) - set(SPEC_NAMES))
    if unknown:
        raise BatchError(f"unknown batch specs: {unknown}")

    runs_root = repo_root / "runs"
    batch_directory = runs_root / f"batch_{batch_id}"
    state_path = batch_directory / "state.json"
    config_path = batch_directory / "config.json"
    state = _load_state(state_path, batch_id)

    for spec_name in spec_names:
        state = await _run_record(
            state,
            state_path=state_path,
            runs_root=runs_root,
            batch_id=batch_id,
            spec_name=spec_name,
            agent="classic",
            seed=0,
            budget=1,
            executor=executor,
            on_completed=on_completed,
        )

    if config_path.is_file():
        document = load_batch_config(config_path)
        if document.config.batch_id != batch_id:
            raise BatchError("stored batch config belongs to another batch id")
    else:
        calibration = _calibration_seconds(state, spec_names)
        budget, seeds, estimate, reason = choose_experiment_shape(
            calibration,
            duration_limit_seconds=duration_limit_seconds,
            choices=choices,
        )
        config = BatchConfig(
            batch_id=batch_id,
            specs={name: get_spec(name) for name in spec_names},
            budget=budget,
            seeds=seeds,
            proposal_space=PATCH_PROPOSAL_SPACE,
            discovery_policy=DiscoveryPolicy(),
            calibration_seconds=calibration,
            duration_limit_seconds=duration_limit_seconds,
            estimated_total_seconds=estimate,
            selection_reason=reason,
        )
        document = _write_config(config_path, config)

    if state.config_hash is None:
        state = state.model_copy(update={"config_hash": document.config_hash})
        _write_state(state_path, state)
    elif state.config_hash != document.config_hash:
        raise BatchError(
            "state config hash does not match the frozen batch configuration"
        )

    for spec_name in document.config.specs:
        for agent in ("gp", "random"):
            for seed in document.config.seeds:
                state = await _run_record(
                    state,
                    state_path=state_path,
                    runs_root=runs_root,
                    batch_id=batch_id,
                    spec_name=spec_name,
                    agent=agent,
                    seed=seed,
                    budget=document.config.budget,
                    executor=executor,
                    on_completed=on_completed,
                )
    return state


async def run_pixel_batch(
    batch_id: str,
    *,
    repo_root: Path,
    executor: RunExecutor = execute_experiment_run,
    duration_limit_seconds: float = DEFAULT_PIXEL_DURATION_LIMIT_SECONDS,
    choices: Sequence[BudgetChoice] = DEFAULT_PIXEL_BUDGET_CHOICES,
    on_completed: CompletionHook | None = None,
) -> BatchState:
    """Calibrate and run the frozen wifi24 pixel-topology comparison matrix."""

    if not BATCH_ID_PATTERN.fullmatch(batch_id) or batch_id in {".", ".."}:
        raise BatchError(f"invalid batch id: {batch_id!r}")
    runs_root = repo_root / "runs"
    batch_directory = runs_root / f"batch_{batch_id}"
    state_path = batch_directory / "state.json"
    config_path = batch_directory / "config.json"
    state = _load_state(state_path, batch_id)

    state = await _run_record(
        state,
        state_path=state_path,
        runs_root=runs_root,
        batch_id=batch_id,
        spec_name="wifi24",
        agent="preflight_pixel",
        seed=0,
        budget=1,
        executor=executor,
        on_completed=on_completed,
    )

    if config_path.is_file():
        document = load_batch_config(config_path)
        if document.config.experiment_kind != "pixel":
            raise BatchError("stored batch config is not a pixel experiment")
    else:
        preflight = _find_record(state, _run_key("wifi24", "preflight_pixel", 0))
        if (
            preflight is None
            or preflight.status != "completed"
            or preflight.duration_seconds is None
        ):
            raise BatchError("pixel preflight did not produce a usable calibration")
        budget, seeds, estimate, reason = choose_pixel_experiment_shape(
            preflight.duration_seconds,
            duration_limit_seconds=duration_limit_seconds,
            choices=choices,
        )
        config = BatchConfig(
            batch_id=batch_id,
            specs={"wifi24": get_spec("wifi24")},
            budget=budget,
            seeds=seeds,
            proposal_space=WIFI24_PIXEL_PROPOSAL_SPACE,
            discovery_policy=DiscoveryPolicy(),
            calibration_seconds={"wifi24": preflight.duration_seconds},
            duration_limit_seconds=duration_limit_seconds,
            estimated_total_seconds=estimate,
            selection_reason=reason,
            experiment_kind="pixel",
            reference_scores=(
                ReferenceScore(
                    label="Day 2 wifi24 classic",
                    score=0.510190364124435,
                    source_run_id="day2-wifi24-classic-s0",
                ),
                ReferenceScore(
                    label="Day 2 wifi24 parametric GP best",
                    score=0.7726173256030144,
                    source_run_id="day2-wifi24-gp-s505",
                ),
            ),
        )
        document = _write_config(config_path, config)

    if state.config_hash is None:
        state = state.model_copy(update={"config_hash": document.config_hash})
        _write_state(state_path, state)
    elif state.config_hash != document.config_hash:
        raise BatchError(
            "state config hash does not match the frozen pixel batch configuration"
        )

    for agent in ("evolve_pixel", "random_pixel"):
        for seed in document.config.seeds:
            state = await _run_record(
                state,
                state_path=state_path,
                runs_root=runs_root,
                batch_id=batch_id,
                spec_name="wifi24",
                agent=agent,
                seed=seed,
                budget=document.config.budget,
                executor=executor,
                on_completed=on_completed,
            )
    return state


async def run_wire_batch(
    batch_id: str,
    *,
    repo_root: Path,
    executor: RunExecutor = execute_wire_experiment_run,
    duration_limit_seconds: float = DEFAULT_WIRE_DURATION_LIMIT_SECONDS,
    choices: Sequence[BudgetChoice] = DEFAULT_WIRE_BUDGET_CHOICES,
    on_completed: CompletionHook | None = None,
) -> BatchState:
    """Calibrate and run the frozen wifi24 NEC2 meander comparison matrix."""

    if not BATCH_ID_PATTERN.fullmatch(batch_id) or batch_id in {".", ".."}:
        raise BatchError(f"invalid batch id: {batch_id!r}")
    runs_root = repo_root / "runs"
    batch_directory = runs_root / f"batch_{batch_id}"
    state_path = batch_directory / "state.json"
    config_path = batch_directory / "config.json"
    state = _load_state(state_path, batch_id)
    day5 = batch_id.startswith("day5-wire-v6")
    if day5 and choices == DEFAULT_WIRE_BUDGET_CHOICES:
        choices = DAY5_WIRE_BUDGET_CHOICES
    state = await _run_record(
        state,
        state_path=state_path,
        runs_root=runs_root,
        batch_id=batch_id,
        spec_name="wifi24",
        agent="classic",
        seed=0,
        budget=1,
        executor=executor,
        on_completed=on_completed,
    )
    if config_path.is_file():
        document = load_batch_config(config_path)
        if document.config.experiment_kind != "wire":
            raise BatchError("stored batch config is not a wire experiment")
    else:
        preflight = _find_record(state, _run_key("wifi24", "classic", 0))
        if (
            preflight is None
            or preflight.status != "completed"
            or preflight.duration_seconds is None
        ):
            raise BatchError("wire preflight did not produce a usable calibration")
        calibration = {"wifi24": preflight.duration_seconds}
        if day5:
            budget, seeds = DAY5_WIRE_BUDGET_CHOICES[0]
            steady_state_evaluations = 2 * len(seeds) * budget
            estimate = (
                preflight.duration_seconds
                + steady_state_evaluations
                * DAY45_WIRE_STEADY_STATE_SECONDS_PER_EVALUATION
            )
            if estimate > duration_limit_seconds:
                raise BatchError(
                    "the preregistered Day 5 matrix exceeds the duration limit"
                )
            reason = (
                f"Selected fixed Day 5 budget={budget} with {len(seeds)} seeds. "
                f"The cold-start preflight took {preflight.duration_seconds:.3f}s; "
                "the source-addressed Day 4.5 matrix measured 109.345s/401 "
                "evaluations, so its 0.272681s steady-state rate implies "
                f"{estimate:.1f}s total, within the "
                f"{duration_limit_seconds:.1f}s limit."
            )
        else:
            budget, seeds, estimate, reason = choose_experiment_shape(
                calibration,
                duration_limit_seconds=duration_limit_seconds,
                choices=choices,
            )
        wire_spec = get_spec("wifi24").model_copy(update=wire_spec_updates())
        proposal_space = (
            MEANDER_PROPOSAL_SPACE_V21
            if batch_id == "day5-wire-v6r2"
            else MEANDER_PROPOSAL_SPACE_V2
            if day5
            else MEANDER_PROPOSAL_SPACE
        )
        config = BatchConfig(
            batch_id=batch_id,
            specs={"wifi24": wire_spec},
            solver="nec2",
            budget=budget,
            seeds=seeds,
            proposal_space=proposal_space,
            discovery_policy=DiscoveryPolicy(),
            calibration_seconds=calibration,
            duration_limit_seconds=duration_limit_seconds,
            estimated_total_seconds=estimate,
            selection_reason=(
                f"{reason} The classic 30 mm box-straight NEC2 run is the "
                "preflight calibration and frozen reference. Wire scoring is "
                "wire-realized-gain-v2 with adaptive lambda/20 segmentation. "
                f"Proposal space is {proposal_space.version}; GP retains all "
                "observations because the preregistered n=400 suggest benchmark "
                "was 0.0337 seconds, below the 5-second windowing threshold."
            ),
            experiment_kind="wire",
        )
        document = _write_config(config_path, config)
    if state.config_hash is None:
        state = state.model_copy(update={"config_hash": document.config_hash})
        _write_state(state_path, state)
    elif state.config_hash != document.config_hash:
        raise BatchError("state config hash does not match the frozen wire config")
    for agent in ("gp", "random"):
        for seed in document.config.seeds:
            state = await _run_record(
                state,
                state_path=state_path,
                runs_root=runs_root,
                batch_id=batch_id,
                spec_name="wifi24",
                agent=agent,
                seed=seed,
                budget=document.config.budget,
                executor=executor,
                on_completed=on_completed,
            )
    return state


def load_batch_state(path: Path) -> BatchState:
    """Load a state file using its own batch id as an integrity cross-check."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        batch_id = str(raw["batch_id"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise BatchError(f"invalid batch state: {error}") from error
    return _load_state(path, batch_id)
