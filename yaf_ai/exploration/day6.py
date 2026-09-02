"""Recoverable execution helpers for preregistered Day 6 experiments."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.baselines import GPExplorationAgent, RandomSearchBaseline
from yaf_ai.exploration.batch import BatchRunRecord, BatchState
from yaf_ai.exploration.environment import (
    AntennaExplorationEnv,
    ExplorationConfig,
    GeometryProposal,
)
from yaf_ai.exploration.freeform_wire import (
    DUAL_BAND_SCORE_VERSION,
    FREEFORM_FREQUENCY_POINTS,
    FREEFORM_SWEEP_HZ,
    OCFD_PROPOSAL_SPACE,
    build_freeform_wire,
    build_ocfd,
    build_tuned_straight_dipole,
    day6_design_spec,
    freeform_proposal_space,
)
from yaf_ai.exploration.logger import AuditStepRecord, ExplorationLogger
from yaf_ai.optimization.bayesian import BayesianOptimizer

DAY6_BATCH_ID = "day6-freeform"
DAY6_SEEDS = (101, 202, 303, 404, 505)
DAY6_PROBE_SEEDS = (6101, 6102, 6103)
DAY6_BUDGET_CHOICES = (300, 250, 200)
DAY6_DURATION_LIMIT_SECONDS = 3.0 * 60.0 * 60.0
DAY6_EXPLORATION_SEGMENTS_PER_WAVELENGTH = 20
OCFD_GRID_SIZE = 20


class Day6Error(RuntimeError):
    """Raised when a frozen Day 6 prerequisite cannot be satisfied."""


class DimensionProbe(BaseModel):
    """One source-addressed real-NEC2 dimension probe."""

    model_config = ConfigDict(frozen=True)

    node_count: int
    seed: int
    run_id: str
    solver_mode: str
    frequency_points: int
    simulation_seconds: float = Field(ge=0.0)


class ReferenceResult(BaseModel):
    """One frozen classic-reference winner or control."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    step_index: int
    score: float
    band_24_min_s11_db: float
    band_58_min_s11_db: float
    parameters: dict[str, float]

    @property
    def worst_band_s11_db(self) -> float:
        """Return the shallower of the two band minima."""

        return max(self.band_24_min_s11_db, self.band_58_min_s11_db)


class Day6Preflight(BaseModel):
    """Frozen preflight, optimizer, reference, and batch decision."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    batch_id: str = DAY6_BATCH_ID
    created_at: datetime
    probes: tuple[DimensionProbe, ...]
    selected_node_count: int
    selected_space_version: str
    gp_suggestion_seconds_at_300: float = Field(ge=0.0)
    optimizer_window: int | None
    selected_budget: int
    estimated_matrix_seconds: float = Field(ge=0.0)
    ocfd: ReferenceResult | None = None
    straight: ReferenceResult | None = None
    scoring_sanity_passed: bool = False


class Day6BatchConfig(BaseModel):
    """Self-hashed immutable Day 6 matrix configuration."""

    model_config = ConfigDict(frozen=True)

    batch_id: str = DAY6_BATCH_ID
    node_count: int
    proposal_space_version: str
    score_version: str = DUAL_BAND_SCORE_VERSION
    frequency_range_hz: tuple[float, float] = FREEFORM_SWEEP_HZ
    frequency_points: int = FREEFORM_FREQUENCY_POINTS
    solver: Literal["nec2"] = "nec2"
    nec2_segments_per_wavelength: int = DAY6_EXPLORATION_SEGMENTS_PER_WAVELENGTH
    agents: tuple[Literal["gp", "random"], ...] = ("gp", "random")
    seeds: tuple[int, ...] = DAY6_SEEDS
    budget: int
    optimizer_window: int | None
    duration_limit_seconds: float = DAY6_DURATION_LIMIT_SECONDS
    estimated_matrix_seconds: float
    ocfd_run_id: str
    ocfd_score: float
    straight_run_id: str
    straight_score: float
    top_selection_rule: str = (
        "score_desc, run_id_asc, step_index_asc; geometry_hash_deduplicated; top_2"
    )
    discovery_rule: str = (
        "best>=1.10*ocfd and both bands valid <=-6dB with <=5pct gap and "
        "whole-sweep Pearson>=0.8"
    )


class Day6BatchConfigDocument(BaseModel):
    """Hash wrapper for the immutable Day 6 matrix configuration."""

    model_config = ConfigDict(frozen=True)

    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: Day6BatchConfig


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode(
            "utf-8"
        )
    )
    os.replace(temporary, path)


def _config_hash(config: Day6BatchConfig) -> str:
    canonical = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _day6_config(
    *,
    proposal_space_version: str,
    evaluation_budget: int,
    seed: int,
    optimizer_window: int | None = None,
) -> ExplorationConfig:
    return ExplorationConfig(
        spec=day6_design_spec(),
        evaluation_budget=evaluation_budget,
        seed=seed,
        solver="nec2",
        proposal_space_version=proposal_space_version,
        optimizer_window=optimizer_window,
        nec2_segments_per_wavelength=DAY6_EXPLORATION_SEGMENTS_PER_WAVELENGTH,
        fixed_problem_definition=(
            "The 40 mm cube, symmetric single-feed wire, 1.5--6.5 GHz/251-point "
            "sweep, lambda/20 real NEC2 exploration oracle, accepted-power worst-band score, "
            "reference, budget, top-2 rule, and v2.1 discovery gates are fixed."
        ),
        explorable_problem_definition=(
            f"The agent may explore only {proposal_space_version}; invalid physical "
            "centerlines are rejected without consuming budget."
        ),
    )


def deterministic_probe_parameters(node_count: int, seed: int) -> dict[str, float]:
    """Return the first valid uniform 3N proposal under one frozen seed."""

    space = freeform_proposal_space(node_count)
    rng = np.random.default_rng(seed)
    for _ in range(100_000):
        parameters = {
            name: float(rng.uniform(lower, upper))
            for name, (lower, upper) in space.bounds.items()
        }
        try:
            build_freeform_wire(parameters, node_count, "preflight")
        except ValueError:
            continue
        return parameters
    raise Day6Error(f"seed {seed} produced no valid N={node_count} probe")


def _load_steps(repo_root: Path, run_id: str) -> list[AuditStepRecord]:
    path = repo_root / "runs" / run_id / "log.jsonl"
    if not path.is_file():
        raise Day6Error(f"missing run log: {run_id}")
    return ExplorationLogger.load_steps(path)


async def _run_proposals(
    *,
    repo_root: Path,
    run_id: str,
    config: ExplorationConfig,
    proposals: list[GeometryProposal],
) -> list[AuditStepRecord]:
    run_directory = repo_root / "runs" / run_id
    if run_directory.is_dir():
        steps = _load_steps(repo_root, run_id)
        if len(steps) != len(proposals):
            raise Day6Error(
                f"existing run {run_id} has {len(steps)} steps, expected {len(proposals)}"
            )
        return steps
    logger = ExplorationLogger(config=config, runs_root=repo_root / "runs", run_id=run_id)
    environment = AntennaExplorationEnv(config, audit_logger=logger)
    environment.reset()
    try:
        for proposal in proposals:
            await environment.step(proposal)
    except Exception as error:
        logger.write_failure_summary(
            f"{type(error).__name__}: {error}", list(environment.results)
        )
        raise
    environment.finish()
    return _load_steps(repo_root, run_id)


async def run_dimension_preflight(repo_root: Path) -> tuple[DimensionProbe, ...]:
    """Run or load the exact nine preregistered N/seed probes."""

    probes: list[DimensionProbe] = []
    for node_count in (5, 6, 7):
        space = freeform_proposal_space(node_count)
        for seed in DAY6_PROBE_SEEDS:
            run_id = f"day6-freeform-preflight-r3-n{node_count}-s{seed}"
            parameters = deterministic_probe_parameters(node_count, seed)
            proposal = GeometryProposal(
                geometry=build_freeform_wire(parameters, node_count, "preflight"),
                parameters=parameters,
                proposer="preflight",
            )
            config = _day6_config(
                proposal_space_version=space.version,
                evaluation_budget=1,
                seed=seed,
            )
            steps = await _run_proposals(
                repo_root=repo_root,
                run_id=run_id,
                config=config,
                proposals=[proposal],
            )
            step = steps[0]
            probes.append(
                DimensionProbe(
                    node_count=node_count,
                    seed=seed,
                    run_id=run_id,
                    solver_mode=step.solver_mode,
                    frequency_points=int(step.metrics["frequency_points"]),
                    simulation_seconds=step.metrics["simulation_time_seconds"],
                )
            )
    return tuple(probes)


def select_node_count(probes: tuple[DimensionProbe, ...]) -> int:
    """Apply the frozen all-three/subprocess/251/10-second N rule."""

    valid: list[int] = []
    for node_count in (5, 6, 7):
        rows = [probe for probe in probes if probe.node_count == node_count]
        if len(rows) != 3:
            continue
        if all(
            row.solver_mode == "subprocess"
            and row.frequency_points == FREEFORM_FREQUENCY_POINTS
            and row.simulation_seconds <= 10.0
            for row in rows
        ):
            valid.append(node_count)
    if not valid:
        raise Day6Error("no N passed the frozen NEC2 validity preflight")
    return max(valid)


def benchmark_gp_suggestion(node_count: int) -> float:
    """Measure one suggestion after the frozen 300-observation synthetic fill."""

    space = freeform_proposal_space(node_count)
    optimizer = BayesianOptimizer(space.bounds, objective=lambda _point: 0.0, n_initial=3)
    rng = np.random.default_rng(6600 + node_count)
    for _ in range(300):
        point = np.array(
            [rng.uniform(lower, upper) for lower, upper in space.bounds.values()],
            dtype=float,
        )
        optimizer.observe(point, float(rng.normal()))
    state = np.random.get_state()
    np.random.seed(6600 + node_count)
    started = time.perf_counter()
    try:
        optimizer.suggest()
    finally:
        elapsed = time.perf_counter() - started
        np.random.set_state(state)
    return elapsed


def choose_batch_budget(
    probes: tuple[DimensionProbe, ...],
    node_count: int,
    gp_suggestion_seconds: float,
) -> tuple[int, float]:
    """Select the first preregistered budget under the three-hour limit."""

    solver_seconds = max(
        probe.simulation_seconds for probe in probes if probe.node_count == node_count
    )
    for budget in DAY6_BUDGET_CHOICES:
        estimate = 10.0 * budget * (solver_seconds + gp_suggestion_seconds)
        if estimate <= DAY6_DURATION_LIMIT_SECONDS:
            return budget, estimate
    raise Day6Error("no preregistered Day 6 budget fits the measured duration gate")


def _reference_result(run_id: str, step: AuditStepRecord) -> ReferenceResult:
    return ReferenceResult(
        run_id=run_id,
        step_index=step.step_index,
        score=step.score,
        band_24_min_s11_db=step.metrics["band_24_min_s11_db"],
        band_58_min_s11_db=step.metrics["band_58_min_s11_db"],
        parameters=step.proposal_parameters,
    )


async def run_references(repo_root: Path) -> tuple[ReferenceResult, ReferenceResult]:
    """Run/load the frozen 20x20 OCFD scan and straight control."""

    lengths = np.linspace(0.045, 0.069, OCFD_GRID_SIZE)
    offsets = np.linspace(0.0, 0.35, OCFD_GRID_SIZE)
    proposals = [
        GeometryProposal(
            geometry=build_ocfd(float(length), float(offset)),
            parameters={
                "total_length_m": float(length),
                "feed_offset_ratio": float(offset),
            },
            proposer="classic_ocfd",
        )
        for length in lengths
        for offset in offsets
    ]
    ocfd_run_id = "day6-freeform-ocfd-grid"
    ocfd_config = _day6_config(
        proposal_space_version=OCFD_PROPOSAL_SPACE.version,
        evaluation_budget=len(proposals),
        seed=0,
    )
    ocfd_steps = await _run_proposals(
        repo_root=repo_root,
        run_id=ocfd_run_id,
        config=ocfd_config,
        proposals=proposals,
    )
    best_ocfd = min(
        ocfd_steps,
        key=lambda step: (
            -step.score,
            step.proposal_parameters["total_length_m"],
            step.proposal_parameters["feed_offset_ratio"],
        ),
    )

    straight_run_id = "day6-freeform-straight-control"
    straight_geometry = build_tuned_straight_dipole()
    straight_parameters = {
        "total_length_m": float(straight_geometry.metadata["design_features"]["total_length_m"]),
        "feed_offset_ratio": 0.0,
    }
    straight_config = _day6_config(
        proposal_space_version=OCFD_PROPOSAL_SPACE.version,
        evaluation_budget=1,
        seed=0,
    )
    straight_steps = await _run_proposals(
        repo_root=repo_root,
        run_id=straight_run_id,
        config=straight_config,
        proposals=[
            GeometryProposal(
                geometry=straight_geometry,
                parameters=straight_parameters,
                proposer="straight_control",
            )
        ],
    )
    return _reference_result(ocfd_run_id, best_ocfd), _reference_result(
        straight_run_id, straight_steps[0]
    )


def _preflight_path(repo_root: Path) -> Path:
    return repo_root / "runs" / f"batch_{DAY6_BATCH_ID}" / "preflight.json"


async def execute_preflight_and_references(repo_root: Path) -> Day6Preflight:
    """Execute all preregistered gates required before the comparison batch."""

    probes = await run_dimension_preflight(repo_root)
    node_count = select_node_count(probes)
    gp_seconds = benchmark_gp_suggestion(node_count)
    optimizer_window = 200 if gp_seconds > 5.0 else None
    budget, estimate = choose_batch_budget(probes, node_count, gp_seconds)
    ocfd, straight = await run_references(repo_root)
    sanity = ocfd.score > straight.score and ocfd.worst_band_s11_db < straight.worst_band_s11_db
    document = Day6Preflight(
        created_at=datetime.now(UTC),
        probes=probes,
        selected_node_count=node_count,
        selected_space_version=freeform_proposal_space(node_count).version,
        gp_suggestion_seconds_at_300=gp_seconds,
        optimizer_window=optimizer_window,
        selected_budget=budget,
        estimated_matrix_seconds=estimate,
        ocfd=ocfd,
        straight=straight,
        scoring_sanity_passed=sanity,
    )
    _write_json(_preflight_path(repo_root), document.model_dump(mode="json"))
    if not sanity:
        raise Day6Error("invalid_scoring_preflight: OCFD did not beat straight control")
    return document


def load_preflight(repo_root: Path) -> Day6Preflight:
    """Load the completed preflight decision used to create batch config."""

    path = _preflight_path(repo_root)
    if not path.is_file():
        raise Day6Error("Day 6 preflight.json is missing")
    return Day6Preflight.model_validate_json(path.read_text(encoding="utf-8"))


def _state_path(repo_root: Path) -> Path:
    return repo_root / "runs" / f"batch_{DAY6_BATCH_ID}" / "state.json"


def _batch_config_path(repo_root: Path) -> Path:
    return repo_root / "runs" / f"batch_{DAY6_BATCH_ID}" / "config.json"


def write_batch_config(repo_root: Path, preflight: Day6Preflight) -> Day6BatchConfigDocument:
    """Freeze the comparison matrix from committed preflight evidence."""

    if not preflight.scoring_sanity_passed or preflight.ocfd is None or preflight.straight is None:
        raise Day6Error("batch cannot start before a passing scoring preflight")
    config = Day6BatchConfig(
        node_count=preflight.selected_node_count,
        proposal_space_version=preflight.selected_space_version,
        budget=preflight.selected_budget,
        optimizer_window=preflight.optimizer_window,
        estimated_matrix_seconds=preflight.estimated_matrix_seconds,
        ocfd_run_id=preflight.ocfd.run_id,
        ocfd_score=preflight.ocfd.score,
        straight_run_id=preflight.straight.run_id,
        straight_score=preflight.straight.score,
    )
    document = Day6BatchConfigDocument(config_hash=_config_hash(config), config=config)
    path = _batch_config_path(repo_root)
    if path.is_file():
        existing = Day6BatchConfigDocument.model_validate_json(path.read_text(encoding="utf-8"))
        if existing != document:
            raise Day6Error("stored Day 6 config differs from the frozen preflight")
        return existing
    _write_json(path, document.model_dump(mode="json"))
    return document


def _load_state(repo_root: Path) -> BatchState:
    path = _state_path(repo_root)
    if not path.is_file():
        return BatchState(batch_id=DAY6_BATCH_ID)
    state = BatchState.model_validate_json(path.read_text(encoding="utf-8"))
    if state.batch_id != DAY6_BATCH_ID:
        raise Day6Error("stored state belongs to a different batch")
    return state


def _write_state(repo_root: Path, state: BatchState) -> None:
    _write_json(_state_path(repo_root), state.model_dump(mode="json"))


def _replace_record(state: BatchState, replacement: BatchRunRecord) -> BatchState:
    records = list(state.runs)
    index = next(
        (position for position, record in enumerate(records) if record.run_key == replacement.run_key),
        None,
    )
    if index is None:
        records.append(replacement)
    else:
        records[index] = replacement
    return state.model_copy(update={"runs": tuple(records)})


async def _execute_matrix_run(
    repo_root: Path,
    record: BatchRunRecord,
    config: Day6BatchConfig,
) -> None:
    exploration_config = _day6_config(
        proposal_space_version=config.proposal_space_version,
        evaluation_budget=config.budget,
        seed=record.seed,
        optimizer_window=config.optimizer_window,
    )
    logger = ExplorationLogger(
        config=exploration_config,
        runs_root=repo_root / "runs",
        run_id=record.run_id,
    )
    environment = AntennaExplorationEnv(exploration_config, audit_logger=logger)
    environment.reset()
    agent = (
        GPExplorationAgent(exploration_config)
        if record.agent == "gp"
        else RandomSearchBaseline(exploration_config)
    )
    try:
        await agent.run(environment)
    except Exception as error:
        logger.write_failure_summary(
            f"{type(error).__name__}: {error}", list(environment.results)
        )
        raise
    environment.finish()


async def run_day6_batch(repo_root: Path) -> BatchState:
    """Run or resume the frozen sequential GP/random comparison matrix."""

    document = write_batch_config(repo_root, load_preflight(repo_root))
    state = _load_state(repo_root)
    if state.config_hash is None:
        state = state.model_copy(update={"config_hash": document.config_hash})
        _write_state(repo_root, state)
    elif state.config_hash != document.config_hash:
        raise Day6Error("Day 6 state/config hash mismatch")
    for agent in document.config.agents:
        for seed in document.config.seeds:
            run_key = f"dual:{agent}:{seed}"
            existing = next((record for record in state.runs if record.run_key == run_key), None)
            if existing is not None and existing.status in {"completed", "failed"}:
                print(f"SKIP {existing.run_id} status={existing.status}", flush=True)
                continue
            if existing is not None and existing.status == "running":
                existing = existing.model_copy(
                    update={
                        "status": "failed",
                        "error": "interrupted before a complete summary was recorded",
                        "finished_at": datetime.now(UTC),
                    }
                )
                state = _replace_record(state, existing)
                _write_state(repo_root, state)
                continue
            started_at = datetime.now(UTC)
            running = BatchRunRecord(
                run_key=run_key,
                run_id=f"day6-freeform-dual-{agent}-s{seed}",
                spec_name="dual",
                agent=agent,
                seed=seed,
                budget=document.config.budget,
                status="running",
                started_at=started_at,
            )
            state = _replace_record(state, running)
            _write_state(repo_root, state)
            print(f"START {running.run_id} budget={running.budget}", flush=True)
            started = time.perf_counter()
            try:
                await _execute_matrix_run(repo_root, running, document.config)
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
            _write_state(repo_root, state)
            print(
                f"{finished.status.upper()} {finished.run_id} "
                f"seconds={finished.duration_seconds:.3f}",
                flush=True,
            )
    return state


def load_day6_batch_config(repo_root: Path) -> Day6BatchConfigDocument:
    """Load and integrity-check the frozen matrix configuration."""

    path = _batch_config_path(repo_root)
    document = Day6BatchConfigDocument.model_validate_json(path.read_text(encoding="utf-8"))
    if _config_hash(document.config) != document.config_hash:
        raise Day6Error("Day 6 batch config hash mismatch")
    return document
