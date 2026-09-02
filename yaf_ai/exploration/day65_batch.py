"""Preregistered Day 6.5 restarted-ES versus random exploration batch."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.batch import BatchRunRecord, BatchState
from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    ExplorationConfig,
    GeometryProposal,
    StepResult,
)
from yaf_ai.exploration.freeform_wire import (
    DUAL_BAND_SCORE_VERSION,
    DUAL_BAND_VALIDITY_BONUS,
    FREEFORM_FREQUENCY_POINTS,
    FREEFORM_SWEEP_HZ,
    build_freeform_wire,
    day6_design_spec,
    freeform_proposal_space,
)
from yaf_ai.exploration.logger import ExplorationLogger
from yaf_ai.exploration.proposal_space import ProposalSpace

DAY65_BATCH_ID = "day65-freeform-v2"
DAY65_NODE_COUNT = 7
DAY65_SEEDS = (101, 202, 303)
DAY65_BUDGET = 500
DAY65_AGENTS: tuple[Literal["es", "random"], ...] = ("es", "random")
DAY65_NEC2_DENSITY = 20
DAY65_OCFD_RUN_ID = "day6-freeform-ocfd-grid"
DAY65_OCFD_SCORE = 0.617137421
ES_INITIAL_SIGMA = 0.15
ES_MIN_SIGMA = 0.01
ES_MAX_SIGMA = 0.30
ES_ADAPTATION_BLOCK = 20
ES_SUCCESS_TARGET = 0.20
ES_SIGMA_FACTOR = 1.5
ES_RESTART_STAGNATION = 75


class Day65BatchError(RuntimeError):
    """Raised when the frozen v2 batch cannot continue reproducibly."""


class Day65BatchConfig(BaseModel):
    """Self-hashed scientific and optimizer definition for the v2 hunt."""

    model_config = ConfigDict(frozen=True)

    batch_id: str = DAY65_BATCH_ID
    proposal_space_version: str = freeform_proposal_space(DAY65_NODE_COUNT).version
    dimensions: int = 3 * DAY65_NODE_COUNT
    frequency_range_hz: tuple[float, float] = FREEFORM_SWEEP_HZ
    frequency_points: int = FREEFORM_FREQUENCY_POINTS
    solver: Literal["nec2"] = "nec2"
    nec2_segments_per_wavelength: int = DAY65_NEC2_DENSITY
    agents: tuple[Literal["es", "random"], ...] = DAY65_AGENTS
    seeds: tuple[int, ...] = DAY65_SEEDS
    budget: int = DAY65_BUDGET
    score_version: str = DUAL_BAND_SCORE_VERSION
    validity_bonus: float = DUAL_BAND_VALIDITY_BONUS
    es_initial_sigma: float = ES_INITIAL_SIGMA
    es_sigma_bounds: tuple[float, float] = (ES_MIN_SIGMA, ES_MAX_SIGMA)
    es_adaptation_block: int = ES_ADAPTATION_BLOCK
    es_success_target: float = ES_SUCCESS_TARGET
    es_sigma_factor: float = ES_SIGMA_FACTOR
    es_restart_stagnation: int = ES_RESTART_STAGNATION
    ocfd_run_id: str = DAY65_OCFD_RUN_ID
    ocfd_score: float = DAY65_OCFD_SCORE
    top_selection_rule: str = (
        "base_score_desc, run_id_asc, step_index_asc; geometry_hash_deduplicated; top_2"
    )
    discovery_rule: str = (
        "base_score>=1.10*ocfd and both bands valid <=-6dB with <=5pct gap "
        "and whole-sweep Pearson>=0.8"
    )


class Day65BatchConfigDocument(BaseModel):
    """Stable hash wrapper for the frozen v2 batch."""

    model_config = ConfigDict(frozen=True)

    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: Day65BatchConfig


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _config_hash(config: Day65BatchConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def day65_batch_config_document() -> Day65BatchConfigDocument:
    """Return the immutable v2 batch config and its content hash."""

    config = Day65BatchConfig()
    return Day65BatchConfigDocument(config_hash=_config_hash(config), config=config)


def _exploration_config(seed: int) -> ExplorationConfig:
    return ExplorationConfig(
        spec=day6_design_spec(),
        evaluation_budget=DAY65_BUDGET,
        seed=seed,
        solver="nec2",
        proposal_space_version=freeform_proposal_space(DAY65_NODE_COUNT).version,
        nec2_segments_per_wavelength=DAY65_NEC2_DENSITY,
        fixed_problem_definition=(
            "Day 6.5 v2 freezes the N=7 symmetric 40 mm freeform space, real "
            "lambda/20 NEC2, 1.5--6.5 GHz/251 points, budget 500, base worst-band "
            "accepted-power score, +0.25 ES-only validity shaping, three seeds, "
            "OCFD reference, top-2 rule, and unchanged v2.1 verdict gates."
        ),
        explorable_problem_definition=(
            "ES or Random may explore only the shared freeform-wire-3d-v1-n7 "
            "coordinate bounds; invalid geometry is rejected without budget cost."
        ),
    )


def reflect_normalized(values: NDArray[np.float64]) -> NDArray[np.float64]:
    """Reflect arbitrary normalized coordinates into the closed unit interval."""

    wrapped = np.mod(values, 2.0)
    reflected: NDArray[np.float64] = np.where(wrapped <= 1.0, wrapped, 2.0 - wrapped)
    return reflected


class RestartedEvolutionStrategy:
    """Deterministic preregistered restarted (1+1)-ES in normalized space."""

    def __init__(self, config: ExplorationConfig) -> None:
        self.config = config
        self.space = freeform_proposal_space(DAY65_NODE_COUNT)
        self._names = tuple(self.space.bounds)
        self._rng = np.random.default_rng(config.seed)
        self._parent: NDArray[np.float64] | None = None
        self._parent_search_score: float | None = None
        self._pending: NDArray[np.float64] | None = None
        self._pending_restart = False
        self._sigma = ES_INITIAL_SIGMA
        self._block_accepted = 0
        self._block_successes = 0
        self._consecutive_non_improvements = 0

    @property
    def sigma(self) -> float:
        """Current normalized mutation scale."""

        return self._sigma

    @property
    def restart_pending(self) -> bool:
        """Whether the next accepted proposal starts a new trajectory."""

        return self._pending_restart

    def _parameters(self, normalized: NDArray[np.float64]) -> dict[str, float]:
        parameters: dict[str, float] = {}
        for name, value in zip(self._names, normalized, strict=True):
            lower, upper = self.space.bounds[name]
            parameters[name] = float(lower + value * (upper - lower))
        return parameters

    def _draw(self) -> NDArray[np.float64]:
        if self._parent is None or self._pending_restart:
            return self._rng.random(len(self._names))
        return reflect_normalized(
            self._parent + self._rng.normal(0.0, self._sigma, len(self._names))
        )

    def propose(self, environment: AntennaExplorationEnv) -> GeometryProposal:
        """Draw until valid, auditing every rejected geometry without budget cost."""

        while True:
            normalized = self._draw()
            parameters = self._parameters(normalized)
            try:
                geometry = build_freeform_wire(parameters, DAY65_NODE_COUNT, "es")
            except ValueError as error:
                environment.record_parameter_rejection(parameters, "es", str(error))
                continue
            self._pending = normalized
            return GeometryProposal(
                geometry=geometry,
                parameters=parameters,
                proposer="es",
            )

    def observe(self, result: StepResult) -> None:
        """Update the local incumbent, 1/5-rule scale, and restart counter."""

        if self._pending is None:
            raise Day65BatchError("ES observe called without a pending proposal")
        search_score = result.metrics["search_score"]
        if self._parent is None or self._pending_restart:
            self._parent = self._pending.copy()
            self._parent_search_score = search_score
            self._pending_restart = False
            self._sigma = ES_INITIAL_SIGMA
            self._block_accepted = 0
            self._block_successes = 0
            self._consecutive_non_improvements = 0
            return
        if self._parent_search_score is None:
            raise Day65BatchError("ES parent score is missing")
        success = search_score > self._parent_search_score
        if success:
            self._parent = self._pending.copy()
            self._parent_search_score = search_score
            self._block_successes += 1
            self._consecutive_non_improvements = 0
        else:
            self._consecutive_non_improvements += 1
        self._block_accepted += 1
        if self._block_accepted == ES_ADAPTATION_BLOCK:
            success_fraction = self._block_successes / ES_ADAPTATION_BLOCK
            if success_fraction > ES_SUCCESS_TARGET:
                self._sigma = min(ES_MAX_SIGMA, self._sigma * ES_SIGMA_FACTOR)
            else:
                self._sigma = max(ES_MIN_SIGMA, self._sigma / ES_SIGMA_FACTOR)
            self._block_accepted = 0
            self._block_successes = 0
        if self._consecutive_non_improvements >= ES_RESTART_STAGNATION:
            self._pending_restart = True

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        """Consume exactly the accepted-evaluation budget."""

        results: list[StepResult] = []
        while environment.budget_remaining > 0:
            result = await environment.step(self.propose(environment))
            self.observe(result)
            results.append(result)
        return results


class AuditedFreeformRandom:
    """Uniform random baseline with generator-level rejection evidence."""

    def __init__(self, config: ExplorationConfig) -> None:
        self.config = config
        self.space: ProposalSpace = freeform_proposal_space(DAY65_NODE_COUNT)
        self._rng = np.random.default_rng(config.seed)

    def propose(self, environment: AntennaExplorationEnv) -> GeometryProposal:
        """Return the next valid uniform proposal while auditing invalid draws."""

        while True:
            parameters = {
                name: float(self._rng.uniform(lower, upper))
                for name, (lower, upper) in self.space.bounds.items()
            }
            try:
                geometry = build_freeform_wire(parameters, DAY65_NODE_COUNT, "random")
            except ValueError as error:
                environment.record_parameter_rejection(parameters, "random", str(error))
                continue
            return GeometryProposal(
                geometry=geometry,
                parameters=parameters,
                proposer="random",
            )

    async def run(self, environment: AntennaExplorationEnv) -> list[StepResult]:
        """Consume exactly the accepted-evaluation budget without feedback."""

        results: list[StepResult] = []
        while environment.budget_remaining > 0:
            results.append(await environment.step(self.propose(environment)))
        return results


def _batch_root(repo_root: Path) -> Path:
    return repo_root / "runs" / f"batch_{DAY65_BATCH_ID}"


def _state_path(repo_root: Path) -> Path:
    return _batch_root(repo_root) / "state.json"


def _config_path(repo_root: Path) -> Path:
    return _batch_root(repo_root) / "config.json"


def write_day65_batch_config(repo_root: Path) -> Day65BatchConfigDocument:
    """Persist or integrity-check the frozen batch configuration."""

    document = day65_batch_config_document()
    path = _config_path(repo_root)
    if path.is_file():
        stored = Day65BatchConfigDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if stored != document:
            raise Day65BatchError("stored Day 6.5 batch config changed")
        return stored
    _write_json(path, document.model_dump(mode="json"))
    return document


def _load_state(repo_root: Path) -> BatchState:
    path = _state_path(repo_root)
    if not path.is_file():
        return BatchState(batch_id=DAY65_BATCH_ID)
    state = BatchState.model_validate_json(path.read_text(encoding="utf-8"))
    if state.batch_id != DAY65_BATCH_ID:
        raise Day65BatchError("stored state belongs to another batch")
    return state


def _replace_record(state: BatchState, replacement: BatchRunRecord) -> BatchState:
    records = list(state.runs)
    index = next(
        (
            position
            for position, record in enumerate(records)
            if record.run_key == replacement.run_key
        ),
        None,
    )
    if index is None:
        records.append(replacement)
    else:
        records[index] = replacement
    return state.model_copy(update={"runs": tuple(records)})


async def _execute_run(repo_root: Path, record: BatchRunRecord) -> None:
    config = _exploration_config(record.seed)
    logger = ExplorationLogger(
        config=config,
        runs_root=repo_root / "runs",
        run_id=record.run_id,
    )
    environment = AntennaExplorationEnv(config, audit_logger=logger)
    environment.reset()
    agent = RestartedEvolutionStrategy(config) if record.agent == "es" else AuditedFreeformRandom(config)
    try:
        await agent.run(environment)
    except Exception as error:
        logger.write_failure_summary(
            f"{type(error).__name__}: {error}", list(environment.results)
        )
        raise
    environment.finish()


async def run_day65_batch(repo_root: Path) -> BatchState:
    """Run the frozen six-cell ES/random matrix sequentially."""

    document = write_day65_batch_config(repo_root)
    state = _load_state(repo_root)
    if state.config_hash is None:
        state = state.model_copy(update={"config_hash": document.config_hash})
        _write_json(_state_path(repo_root), state.model_dump(mode="json"))
    elif state.config_hash != document.config_hash:
        raise Day65BatchError("Day 6.5 state/config hash mismatch")
    for agent in document.config.agents:
        for seed in document.config.seeds:
            run_key = f"dual:{agent}:{seed}"
            existing = next(
                (record for record in state.runs if record.run_key == run_key), None
            )
            if existing is not None and existing.status in {"completed", "failed"}:
                print(f"SKIP {existing.run_id} status={existing.status}", flush=True)
                continue
            if existing is not None and existing.status == "running":
                failed = existing.model_copy(
                    update={
                        "status": "failed",
                        "error": "interrupted before a complete summary was recorded",
                        "finished_at": datetime.now(UTC),
                    }
                )
                state = _replace_record(state, failed)
                _write_json(_state_path(repo_root), state.model_dump(mode="json"))
                continue
            started_at = datetime.now(UTC)
            running = BatchRunRecord(
                run_key=run_key,
                run_id=f"{DAY65_BATCH_ID}-dual-{agent}-s{seed}",
                spec_name="dual",
                agent=agent,
                seed=seed,
                budget=document.config.budget,
                status="running",
                started_at=started_at,
            )
            state = _replace_record(state, running)
            _write_json(_state_path(repo_root), state.model_dump(mode="json"))
            print(f"START {running.run_id} budget={running.budget}", flush=True)
            started = time.perf_counter()
            try:
                await _execute_run(repo_root, running)
            except Exception as error:
                finished = running.model_copy(
                    update={
                        "status": "failed",
                        "error": f"{type(error).__name__}: {error}",
                        "duration_seconds": time.perf_counter() - started,
                        "finished_at": datetime.now(UTC),
                    }
                )
            else:
                finished = running.model_copy(
                    update={
                        "status": "completed",
                        "duration_seconds": time.perf_counter() - started,
                        "finished_at": datetime.now(UTC),
                    }
                )
            state = _replace_record(state, finished)
            _write_json(_state_path(repo_root), state.model_dump(mode="json"))
            print(
                f"{finished.status.upper()} {finished.run_id} "
                f"seconds={finished.duration_seconds:.3f}",
                flush=True,
            )
    return state
