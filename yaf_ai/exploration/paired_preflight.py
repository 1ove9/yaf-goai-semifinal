"""Frozen 20-pair NEC2 timing preflight for the semifinal paired study."""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.paired_meander import (
    PairedMeanderError,
    audit_trajectory,
    build_state_geometry,
    iter_manual_pairs,
    pair_hash,
    select_timing_preflight_pairs,
)
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRunConfig,
    _append_jsonl,
    _evaluation,
    _write_json,
)
from yaf_ai.exploration.paired_solver import PairedNEC2Solver

PREFLIGHT_RUN_ID = "semifinal-paired-budget-preflight"
PREFLIGHT_PREREGISTRATION_COMMIT = "374fb05"
PREFLIGHT_PAIR_COUNT = 20
T_WINDOW_SECONDS = 43_200
PARALLEL_WORKERS = 1
PREFLIGHT_P95_METHOD: Literal["higher"] = "higher"


class PreflightTimingRow(BaseModel):
    """One measured accepted pair in frozen selected order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_index: int = Field(ge=0, lt=PREFLIGHT_PAIR_COUNT)
    pair_hash: str
    elapsed_seconds: float = Field(gt=0.0)


class PairedPreflightSummary(BaseModel):
    """Archive-compatible success or terminal all-or-nothing failure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    result_status: Literal["completed", "execution_failed"]
    run_id: str = PREFLIGHT_RUN_ID
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str
    config: dict[str, Any]
    steps_completed: int = Field(ge=0, le=PREFLIGHT_PAIR_COUNT)
    evaluation_budget: int = PREFLIGHT_PAIR_COUNT
    solver_mode_counts: dict[str, int]
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    input_pair_count: int = 5_184
    legal_pair_count: int = Field(ge=0, le=5_184)
    selected_pair_hashes: tuple[str, ...]
    timing_rows: tuple[PreflightTimingRow, ...]
    p95_method: Literal["higher"] = "higher"
    t_pair_p95_seconds: float | None = Field(default=None, gt=0.0)
    t_window_seconds: int = T_WINDOW_SECONDS
    parallel_workers: int = PARALLEL_WORKERS
    raw_budget: int | None = Field(default=None, ge=0)
    budget: int | None = Field(default=None, ge=0, le=300)
    budget_classification: str | None = None
    failure_message: str | None = None


def _classification(budget: int) -> str:
    if budget >= 200:
        return "three_seed_descriptive_statistics"
    if budget >= 80:
        return "exploratory_small_sample"
    return "infeasible_within_submission_window"


def calculate_budget(times: tuple[float, ...]) -> tuple[float, int, int, str]:
    """Apply the frozen conservative P95 and budget formula."""

    if len(times) != PREFLIGHT_PAIR_COUNT or any(
        not math.isfinite(value) or value <= 0.0 for value in times
    ):
        raise PairedMeanderError("budget calculation requires 20 positive finite times")
    p95 = float(
        np.quantile(
            np.asarray(times, dtype=float),
            0.95,
            method=PREFLIGHT_P95_METHOD,
        )
    )
    raw_budget = math.floor(
        70 * T_WINDOW_SECONDS * PARALLEL_WORKERS / (100 * 9 * p95)
    )
    budget = min(300, raw_budget)
    return p95, raw_budget, budget, _classification(budget)


async def run_paired_preflight(
    repo_root: Path,
    solver: PairedNEC2Solver | None = None,
) -> PairedPreflightSummary:
    """Run the only authorized paired numerical work for this task."""

    if T_WINDOW_SECONDS != 43_200 or PARALLEL_WORKERS != 1:
        raise PairedMeanderError("frozen preflight integers changed")
    run_directory = repo_root / "runs" / PREFLIGHT_RUN_ID
    run_directory.mkdir(parents=True, exist_ok=False)
    log_path = run_directory / "log.jsonl"
    log_path.touch()
    summary_path = run_directory / "summary.json"
    started_at = datetime.now(UTC)
    input_count = sum(1 for _row in iter_manual_pairs())
    if input_count != 5_184:
        raise PairedMeanderError("manual pair iterator no longer contains 5,184 rows")
    legal_count = sum(
        1
        for _hardware_index, _pair_index, proposal in iter_manual_pairs()
        if audit_trajectory(proposal).valid
    )
    selected = select_timing_preflight_pairs(
        proposal for _hardware_index, _pair_index, proposal in iter_manual_pairs()
    )
    if len(selected) != PREFLIGHT_PAIR_COUNT:
        raise PairedMeanderError("timing selector did not return exactly 20 pairs")
    selected_hashes = tuple(pair_hash(proposal) for proposal in selected)
    config_model = PairedRunConfig(
        run_id=PREFLIGHT_RUN_ID,
        agent="manual",
        seed=0,
        evaluation_budget=PREFLIGHT_PAIR_COUNT,
        anchor_released=False,
        openems_cross_check_authorized=False,
        preregistration_commit=PREFLIGHT_PREREGISTRATION_COMMIT,
    )
    config = {
        **config_model.model_dump(mode="json"),
        "t_window_seconds": T_WINDOW_SECONDS,
        "parallel_workers": PARALLEL_WORKERS,
        "p95_method": PREFLIGHT_P95_METHOD,
        "selector_input_pair_count": input_count,
        "selected_pair_hashes": selected_hashes,
    }
    config_hash = hashlib.sha256(
        json.dumps(
            config, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()
    paired_solver = PairedNEC2Solver() if solver is None else solver
    timings: list[PreflightTimingRow] = []
    subprocess_curves = 0
    try:
        for step_index, proposal in enumerate(selected):
            tick = time.perf_counter()
            trajectory = audit_trajectory(proposal)
            if not trajectory.valid:
                raise PairedMeanderError("frozen preflight selector emitted an invalid pair")
            geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
            geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
            curve_a = await paired_solver(geometry_a, "A", tuple(
                proposal_frequency for proposal_frequency in _state_frequencies("A")
            ))
            curve_b = await paired_solver(geometry_b, "B", tuple(
                proposal_frequency for proposal_frequency in _state_frequencies("B")
            ))
            if curve_a.solver_mode != "subprocess" or curve_b.solver_mode != "subprocess":
                raise PairedMeanderError("preflight received a non-subprocess curve")
            evaluation = _evaluation(proposal, curve_a, curve_b)
            record = PairedEvaluationRecord(
                run_id=PREFLIGHT_RUN_ID,
                step_index=step_index,
                proposal_index=step_index,
                timestamp=datetime.now(UTC),
                proposer=proposal.proposer,
                proposal=proposal,
                evaluation=evaluation,
            )
            _append_jsonl(log_path, record.model_dump(mode="json"))
            elapsed = time.perf_counter() - tick
            timings.append(
                PreflightTimingRow(
                    step_index=step_index,
                    pair_hash=evaluation.pair_hash,
                    elapsed_seconds=elapsed,
                )
            )
            subprocess_curves += 2
    except Exception as error:
        failure = PairedPreflightSummary(
            result_status="execution_failed",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            config_hash=config_hash,
            config=config,
            steps_completed=len(timings),
            solver_mode_counts={"subprocess": subprocess_curves},
            legal_pair_count=legal_count,
            selected_pair_hashes=selected_hashes,
            timing_rows=tuple(timings),
            failure_message=f"{type(error).__name__}: {error}",
        )
        _write_json(summary_path, failure.model_dump(mode="json"))
        return failure
    time_values = tuple(row.elapsed_seconds for row in timings)
    p95, raw_budget, budget, classification = calculate_budget(time_values)
    summary = PairedPreflightSummary(
        result_status="completed",
        started_at=started_at,
        finished_at=datetime.now(UTC),
        config_hash=config_hash,
        config=config,
        steps_completed=PREFLIGHT_PAIR_COUNT,
        solver_mode_counts={"subprocess": subprocess_curves},
        legal_pair_count=legal_count,
        selected_pair_hashes=selected_hashes,
        timing_rows=tuple(timings),
        t_pair_p95_seconds=p95,
        raw_budget=raw_budget,
        budget=budget,
        budget_classification=classification,
    )
    _write_json(summary_path, summary.model_dump(mode="json"))
    return summary


def _state_frequencies(state: Literal["A", "B"]) -> tuple[float, ...]:
    from yaf_ai.exploration.paired_meander import (  # noqa: PLC0415
        STATE_A_FREQUENCIES_HZ,
        STATE_B_FREQUENCIES_HZ,
    )

    return STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ
