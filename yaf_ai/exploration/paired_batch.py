"""Frozen, provenance-gated nine-run paired-state NEC2 batch."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from yaf_ai.exploration.paired_agents import (
    PairedRandomProposer,
    PairedRestartedES,
    encode_warm_parent,
)
from yaf_ai.exploration.paired_baseline import ManualWarmParentDocument
from yaf_ai.exploration.paired_meander import (
    PairedSolver,
    SearchCurve,
    StateLabel,
    build_state_geometry,
    hardware_hash,
    pair_hash,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_preflight import PairedPreflightSummary
from yaf_ai.exploration.paired_runner import (
    PairedAdaptiveProposer,
    PairedEvaluationRecord,
    PairedRunConfig,
    PairedRunError,
    PairedRunSummary,
    run_paired_adaptive,
)
from yaf_ai.exploration.paired_solver import PairedNEC2Solver
from yaf_core.domain.geometry import Geometry

AgentName = Literal["random", "es-cold", "es-warm"]

BATCH_PREREGISTRATION_COMMIT = "abeca0e58e080bdeb297c8169d3c931694daa3ec"
BUDGET_SOURCE_COMMIT = "253090b80df23184cb8521cbbe77af1e38a9b734"
BUDGET_SOURCE_SUMMARY_SHA256 = (
    "b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138"
)
BUDGET_SOURCE_CONFIG_HASH = (
    "d618134588d0db607e21638fdffed4ebff3627a669d281b3dfef456bafc43f92"
)
MANUAL_BASELINE_COMMIT = "906835eceeae2e48a652e2b7fa891fd3e8461440"
WARM_PARENT_RUN_ID = "semifinal-paired-manual-baseline"
WARM_PARENT_PAIR_HASH = (
    "e9f13ba6ede326e3adc4a48ba0a7658c0ca712434550ed98bffab681d262b321"
)
WARM_PARENT_HARDWARE_HASH = (
    "d8d7e70ee2f085ca4c9a73b37c9c69a63bd02b97bdb0307d4fda0934642ca933"
)
WARM_PARENT_STATE_A_HASH = (
    "cc6d3d8b48d03d8843c4663eb3018b55c10cec15f5066c8975537b01019c69e9"
)
WARM_PARENT_STATE_B_HASH = (
    "371fb99d21536e5de565755d55599e778ae9b0cf3fb277c0a155adde4071e783"
)
WARM_PARENT_DOCUMENT_SHA256 = (
    "5d1aef64ac367db741834d94fb42735d4d8670269df376637b52785e59557f08"
)
WARM_PARENT_SOURCE_STEP = 288
WARM_PARENT_HARDWARE_GRID_INDEX = 6
WARM_PARENT_PAIR_GRID_INDEX = 963
WARM_PARENT_SEARCH_SCORE = 0.7845105078918817
FROZEN_EVALUATION_BUDGET = 300
FROZEN_SEEDS = (101, 202, 303)
WARM_PARENT_PATH = Path(
    "artifacts/analysis/semifinal-paired-manual-baseline/warm_parent.json"
)
MANUAL_LOG_PATH = Path(
    "artifacts/runs/semifinal-paired-manual-baseline/log.jsonl"
)
PREFLIGHT_SUMMARY_PATH = Path(
    "artifacts/runs/semifinal-paired-budget-preflight/summary.json"
)
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class PairedBatchError(PairedRunError):
    """Raised before or during the frozen matrix when evidence contracts fail."""


class FrozenAgentCell(BaseModel):
    """One immutable cell of the preregistered matrix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    agent: AgentName
    seed: int


class FrozenBatchInputs(BaseModel):
    """Validated source evidence required before a solver can be constructed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_commit: str
    warm_parent: ManualWarmParentDocument
    warm_parent_source: PairedEvaluationRecord
    preflight: PairedPreflightSummary


FROZEN_AGENT_CELLS = tuple(
    FrozenAgentCell(
        run_id=f"semifinal-paired-{agent}-s{seed}",
        agent=agent,
        seed=seed,
    )
    for agent in ("random", "es-cold", "es-warm")
    for seed in FROZEN_SEEDS
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git(repo_root: Path, *arguments: str) -> bytes:
    try:
        process = subprocess.run(
            ("git", *arguments),
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise PairedBatchError(f"cannot execute git evidence gate: {error}") from error
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise PairedBatchError(
            f"git evidence gate failed for {arguments!r}: {stderr}"
        )
    return process.stdout


def _git_blob(repo_root: Path, commit: str, path: Path) -> bytes:
    return _git(repo_root, "show", f"{commit}:{path.as_posix()}")


def _require_ancestor(repo_root: Path, ancestor: str, descendant: str) -> None:
    try:
        process = subprocess.run(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise PairedBatchError(f"cannot execute git ancestry gate: {error}") from error
    if process.returncode != 0:
        raise PairedBatchError(
            f"required evidence commit {ancestor} is not an ancestor of {descendant}"
        )


def _require_exact_bytes(
    current: bytes,
    committed: bytes,
    expected_sha256: str | None,
    label: str,
) -> None:
    if current != committed:
        raise PairedBatchError(f"{label} differs from its committed evidence blob")
    if expected_sha256 is not None and _sha256(current) != expected_sha256:
        raise PairedBatchError(f"{label} SHA-256 differs from preregistration")


def _find_parent_source(log_bytes: bytes) -> PairedEvaluationRecord:
    selected: list[PairedEvaluationRecord] = []
    try:
        for line in log_bytes.decode("utf-8").splitlines():
            payload = json.loads(line)
            if (
                payload.get("event_type") == "paired_evaluation"
                and payload.get("step_index") == WARM_PARENT_SOURCE_STEP
            ):
                selected.append(PairedEvaluationRecord.model_validate(payload))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise PairedBatchError(f"cannot parse committed manual source log: {error}") from error
    if len(selected) != 1:
        raise PairedBatchError("committed manual source row is not unique")
    return selected[0]


def _validate_parent(
    parent_bytes: bytes,
    manual_log_bytes: bytes,
) -> tuple[ManualWarmParentDocument, PairedEvaluationRecord]:
    if _sha256(parent_bytes) != WARM_PARENT_DOCUMENT_SHA256:
        raise PairedBatchError("warm-parent document SHA-256 differs from preregistration")
    try:
        parent = ManualWarmParentDocument.model_validate_json(parent_bytes)
    except ValueError as error:
        raise PairedBatchError(f"cannot validate warm-parent document: {error}") from error
    expected_scalars = (
        parent.parent_run_id == WARM_PARENT_RUN_ID,
        parent.pair_hash == WARM_PARENT_PAIR_HASH,
        parent.hardware_hash == WARM_PARENT_HARDWARE_HASH,
        parent.state_a_geometry_hash == WARM_PARENT_STATE_A_HASH,
        parent.state_b_geometry_hash == WARM_PARENT_STATE_B_HASH,
        parent.hardware_grid_index == WARM_PARENT_HARDWARE_GRID_INDEX,
        parent.pair_grid_index == WARM_PARENT_PAIR_GRID_INDEX,
        parent.search_score == WARM_PARENT_SEARCH_SCORE,
        parent.baseline_commit is None,
        not parent.valid_pair_search,
        not parent.positive_eligible,
    )
    if not all(expected_scalars):
        raise PairedBatchError("warm-parent document fields differ from preregistration")

    proposal = parent.proposal
    geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
    geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
    if pair_hash(proposal) != WARM_PARENT_PAIR_HASH:
        raise PairedBatchError("warm-parent proposal pair hash does not reconstruct")
    if hardware_hash(proposal.hardware) != WARM_PARENT_HARDWARE_HASH:
        raise PairedBatchError("warm-parent hardware hash does not reconstruct")
    if (
        state_geometry_hash(proposal.hardware, proposal.state_a, geometry_a)
        != WARM_PARENT_STATE_A_HASH
        or state_geometry_hash(proposal.hardware, proposal.state_b, geometry_b)
        != WARM_PARENT_STATE_B_HASH
    ):
        raise PairedBatchError("warm-parent state geometry hash does not reconstruct")
    encoded = tuple(float(value) for value in encode_warm_parent(proposal))
    if encoded != parent.encoded_warm_parent:
        raise PairedBatchError("warm-parent encoding does not round-trip")

    source = _find_parent_source(manual_log_bytes)
    source_evaluation = source.evaluation
    if (
        source.run_id != WARM_PARENT_RUN_ID
        or source.step_index != WARM_PARENT_SOURCE_STEP
        or source.hardware_grid_index != WARM_PARENT_HARDWARE_GRID_INDEX
        or source.pair_grid_index != WARM_PARENT_PAIR_GRID_INDEX
        or source.proposal != proposal
        or source_evaluation.pair_hash != WARM_PARENT_PAIR_HASH
        or source_evaluation.hardware_hash != WARM_PARENT_HARDWARE_HASH
        or source_evaluation.state_a_geometry_hash != WARM_PARENT_STATE_A_HASH
        or source_evaluation.state_b_geometry_hash != WARM_PARENT_STATE_B_HASH
        or source_evaluation.metrics.search_score != WARM_PARENT_SEARCH_SCORE
    ):
        raise PairedBatchError("committed manual source row differs from warm parent")
    return parent, source


def _validate_preflight(summary_bytes: bytes) -> PairedPreflightSummary:
    if _sha256(summary_bytes) != BUDGET_SOURCE_SUMMARY_SHA256:
        raise PairedBatchError("budget-source summary SHA-256 differs from preregistration")
    try:
        summary = PairedPreflightSummary.model_validate_json(summary_bytes)
    except ValueError as error:
        raise PairedBatchError(f"cannot validate budget-source summary: {error}") from error
    if (
        summary.result_status != "completed"
        or summary.config_hash != BUDGET_SOURCE_CONFIG_HASH
        or summary.raw_budget != 907
        or summary.budget != FROZEN_EVALUATION_BUDGET
        or summary.parallel_workers != 1
        or summary.t_pair_p95_seconds != 3.7018278000032296
    ):
        raise PairedBatchError("budget-source fields differ from preregistration")
    return summary


def load_frozen_batch_inputs(repo_root: Path) -> FrozenBatchInputs:
    """Validate Git provenance and all source bytes before solver construction."""

    resolved_root = repo_root.resolve()
    execution_commit = _git(resolved_root, "rev-parse", "HEAD").decode().strip()
    if _FULL_COMMIT.fullmatch(execution_commit) is None:
        raise PairedBatchError("batch execution HEAD is not a full commit hash")
    for ancestor in (
        BATCH_PREREGISTRATION_COMMIT,
        BUDGET_SOURCE_COMMIT,
        MANUAL_BASELINE_COMMIT,
    ):
        _require_ancestor(resolved_root, ancestor, execution_commit)

    parent_current = (resolved_root / WARM_PARENT_PATH).read_bytes()
    parent_committed = _git_blob(
        resolved_root, MANUAL_BASELINE_COMMIT, WARM_PARENT_PATH
    )
    _require_exact_bytes(
        parent_current,
        parent_committed,
        WARM_PARENT_DOCUMENT_SHA256,
        "warm-parent document",
    )
    log_current = (resolved_root / MANUAL_LOG_PATH).read_bytes()
    log_committed = _git_blob(resolved_root, MANUAL_BASELINE_COMMIT, MANUAL_LOG_PATH)
    _require_exact_bytes(log_current, log_committed, None, "manual source log")
    parent, source = _validate_parent(parent_current, log_current)

    preflight_current = (resolved_root / PREFLIGHT_SUMMARY_PATH).read_bytes()
    preflight_committed = _git_blob(
        resolved_root, BUDGET_SOURCE_COMMIT, PREFLIGHT_SUMMARY_PATH
    )
    _require_exact_bytes(
        preflight_current,
        preflight_committed,
        BUDGET_SOURCE_SUMMARY_SHA256,
        "budget-source summary",
    )
    preflight = _validate_preflight(preflight_current)
    return FrozenBatchInputs(
        execution_commit=execution_commit,
        warm_parent=parent,
        warm_parent_source=source,
        preflight=preflight,
    )


def build_agent_run_config(
    cell: FrozenAgentCell,
    inputs: FrozenBatchInputs,
) -> PairedRunConfig:
    """Build one config whose hash carries code, budget, and parent provenance."""

    common: dict[str, object] = {
        "run_id": cell.run_id,
        "agent": cell.agent,
        "seed": cell.seed,
        "evaluation_budget": FROZEN_EVALUATION_BUDGET,
        "anchor_released": False,
        "openems_cross_check_authorized": False,
        "preregistration_commit": BATCH_PREREGISTRATION_COMMIT,
        "execution_commit": inputs.execution_commit,
        "budget_source_summary_sha256": BUDGET_SOURCE_SUMMARY_SHA256,
        "budget_source_config_hash": BUDGET_SOURCE_CONFIG_HASH,
    }
    if cell.agent == "es-warm":
        common.update(
            {
                "manual_baseline_commit": MANUAL_BASELINE_COMMIT,
                "warm_parent_run_id": WARM_PARENT_RUN_ID,
                "warm_parent_pair_hash": WARM_PARENT_PAIR_HASH,
                "warm_parent_document_sha256": WARM_PARENT_DOCUMENT_SHA256,
                "warm_parent_hardware_hash": WARM_PARENT_HARDWARE_HASH,
                "warm_parent_state_a_geometry_hash": WARM_PARENT_STATE_A_HASH,
                "warm_parent_state_b_geometry_hash": WARM_PARENT_STATE_B_HASH,
                "warm_parent_step_index": WARM_PARENT_SOURCE_STEP,
                "warm_parent_hardware_grid_index": WARM_PARENT_HARDWARE_GRID_INDEX,
                "warm_parent_pair_grid_index": WARM_PARENT_PAIR_GRID_INDEX,
                "warm_parent_search_score": WARM_PARENT_SEARCH_SCORE,
            }
        )
    return PairedRunConfig.model_validate(common)


def build_agent_proposer(
    cell: FrozenAgentCell,
    inputs: FrozenBatchInputs,
) -> PairedAdaptiveProposer:
    """Construct the frozen proposer for one matrix cell."""

    if cell.agent == "random":
        return PairedRandomProposer(cell.seed)
    if cell.agent == "es-cold":
        return PairedRestartedES(cell.seed)
    return PairedRestartedES(
        cell.seed,
        warm_parent=inputs.warm_parent.proposal,
        warm_parent_search_score=inputs.warm_parent.search_score,
    )


class _StrictSubprocessSolver:
    """Reject any curve that escapes the real subprocess-only search contract."""

    def __init__(self, solver: PairedSolver) -> None:
        self._solver = solver

    async def __call__(
        self,
        geometry: Geometry,
        state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        curve = await self._solver(geometry, state, frequency_hz)
        if curve.solver_name != "nec2" or curve.solver_mode != "subprocess":
            raise PairedBatchError("agent batch requires real NEC2 subprocess curves")
        if curve.frequency_hz != frequency_hz:
            raise PairedBatchError("agent batch solver changed the frozen frequency table")
        if curve.realized_gain_dbi is not None:
            raise PairedBatchError("agent batch search curves must not contain gain")
        return curve


async def run_frozen_agent_matrix(
    repo_root: Path,
    *,
    solver_factory: Callable[[], PairedSolver] = PairedNEC2Solver,
) -> tuple[PairedRunSummary, ...]:
    """Execute or exactly resume all nine cells after provenance validation."""

    inputs = load_frozen_batch_inputs(repo_root)
    solver = _StrictSubprocessSolver(solver_factory())
    summaries: list[PairedRunSummary] = []
    for cell in FROZEN_AGENT_CELLS:
        summary = await run_paired_adaptive(
            config=build_agent_run_config(cell, inputs),
            proposer=build_agent_proposer(cell, inputs),
            solver=solver,
            runs_root=repo_root.resolve() / "runs",
        )
        if summary.status not in {"completed", "insufficient_feasible_proposals"}:
            raise PairedBatchError(
                f"unexpected terminal status for {cell.run_id}: {summary.status}"
            )
        summaries.append(summary)
    return tuple(summaries)
