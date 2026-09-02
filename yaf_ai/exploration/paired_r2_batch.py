"""Evidence-gated five-seed parent-return ES study."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_agents import decode_normalized, encode_warm_parent
from yaf_ai.exploration.paired_batch import (  # noqa: PLC2701
    BUDGET_SOURCE_COMMIT,
    PairedBatchError,
    _git,
    _git_blob,
    _require_ancestor,
    _require_exact_bytes,
    _StrictSubprocessSolver,
)
from yaf_ai.exploration.paired_candidates import (
    SOURCE_MANIFEST_SHA256,
    CandidateFreezeDocument,
    FrozenCategoryCandidate,
    _canonical_manifest_entry,
    _load_paired_evaluations_bytes,
    _manifest_index,
)
from yaf_ai.exploration.paired_meander import (
    PairedSolver,
    build_state_geometry,
    hardware_hash,
    pair_hash,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_preflight import (
    PREFLIGHT_P95_METHOD,
    PairedPreflightSummary,
)
from yaf_ai.exploration.paired_r2_agents import R2ParentReturnES
from yaf_ai.exploration.paired_runner import (
    PairedEvaluationRecord,
    PairedRunConfig,
    PairedRunSummary,
    _config_hash,
    _load_paired_events,
    _replay_proposer,
    run_paired_adaptive,
)
from yaf_ai.exploration.paired_solver import PairedNEC2Solver

R2_PREREGISTRATION_COMMIT = "eead162e33c5150f741050df4901f3d608bc5ea5"
R2_SOURCE_COMMIT = "a19684b5449774db82b21907cc11c7874287f838"
R2_EFFECT_COMMIT = "4a8222eb7528a24acaa5879e7afa2398f0413740"
R2_FROZEN_PACKAGE_COMMIT = "bdfb9c1"
R2_RUN_ID_PREFIX = "semifinal-paired-r2-es-warm-s"
R2_SEEDS = (101, 202, 303, 404, 505)
R2_EVALUATION_BUDGET = 400

R2_PARENT_SOURCE_RUN_ID = "semifinal-paired-es-warm-s101"
R2_PARENT_SOURCE_STEP = 213
R2_PARENT_PROPOSAL_INDEX = 658
R2_PARENT_SOURCE_LOG_SHA256 = (
    "af5b158d487577d7a07f26186ff66222b34abe05e36bd58596849dc4e3ff6c65"
)
R2_PARENT_SOURCE_SUMMARY_SHA256 = (
    "52cd3ad16c3db5b2f3d98ab2bf394e69d4f6af0381d595d88edd3de3f98e25b7"
)
R2_PARENT_SOURCE_CONFIG_HASH = (
    "7ed5e6758e8ffd554fa2bcd9e323611f46e0e099a5b2fdd9c74f6ec4401e9cde"
)
R2_EFFECT_DOCUMENT_SHA256 = (
    "0e814e2cc85ae0fe361c91a4d7338ae2175369b494eb49cdef8bd165338695d5"
)
R2_PARENT_PAIR_HASH = (
    "8a4ad18c710ec185728fd5bff0e6f16461aea29362024893e1bb6ddd3dcc73ca"
)
R2_PARENT_HARDWARE_HASH = (
    "b6f72349504b6994a10ff9d32ffb7059424073fb25bc2900860f7e1348b9340c"
)
R2_PARENT_STATE_A_GEOMETRY_HASH = (
    "4d8c585c7e4112d1d8aad9d8c33b55642549008cec6649075a75ffa4a4b15b55"
)
R2_PARENT_STATE_B_GEOMETRY_HASH = (
    "84566f8b6ab538d6ff1ae730b2ecd74f445fc127f877f8edb1a53530e509c33e"
)
R2_PARENT_SEARCH_SCORE = 1.0445832225323137
R2_L_MANUAL = 0.21548949210811824
R2_L_REQUIRED = 0.9 * R2_L_MANUAL

R2_BUDGET_SUMMARY_SHA256 = (
    "b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138"
)
R2_BUDGET_CONFIG_HASH = (
    "d618134588d0db607e21638fdffed4ebff3627a669d281b3dfef456bafc43f92"
)
R2_SOURCE_MANIFEST_ENTRY_SHA256 = (
    "5bf1b83868ff96dfa22528b4e245513d3dd964c8fb461c22edc0bb60dea90724"
)

SOURCE_LOG_PATH = Path(
    "artifacts/runs/semifinal-paired-es-warm-s101/log.jsonl"
)
SOURCE_SUMMARY_PATH = Path(
    "artifacts/runs/semifinal-paired-es-warm-s101/summary.json"
)
SOURCE_MANIFEST_PATH = Path("artifacts/runs/manifest.json")
EFFECT_DOCUMENT_PATH = Path(
    "artifacts/analysis/semifinal-paired-agent-batch/frozen_candidates.json"
)
BUDGET_SUMMARY_PATH = Path(
    "artifacts/runs/semifinal-paired-budget-preflight/summary.json"
)

FROZEN_SCIENCE_BLOBS = {
    Path("yaf_ai/exploration/paired_runner.py"): "d2ece9096be6daa86de6b281bb64a8b1150c782e",
    Path("yaf_ai/exploration/paired_solver.py"): "96efa9fe3e755fbca9b31315d96a330bef7291b9",
    Path("yaf_ai/exploration/paired_meander.py"): "98fd67154d5f6a512fdf46b99da1fc273ba8eced",
    Path("yaf_ai/exploration/day65_batch.py"): "5944f5c2f9c892aa0a6860b2ef443f914f6baecc",
    Path("scripts/day65_batch.py"): "365a9ab2ef07de82915931099edc7b9d6f821791",
    Path("yaf_ai/exploration/paired_agents.py"): "0b8b8046611bca0fd2e0c0649277e5594f439f99",
}
R2_CODE_PATHS = (
    Path("yaf_ai/exploration/paired_r2_agents.py"),
    Path("yaf_ai/exploration/paired_r2_batch.py"),
    Path("yaf_ai/exploration/paired_r2_report.py"),
    Path("scripts/paired_r2_batch.py"),
)
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class R2PairedRunConfig(PairedRunConfig):
    """R2-only immutable config whose full provenance enters its hash."""

    agent: Literal["es-r2"] = "es-r2"  # type: ignore[assignment]
    execution_commit: str
    r2_parent_pair_hash: str
    r2_parent_hardware_hash: str
    r2_parent_state_a_geometry_hash: str
    r2_parent_state_b_geometry_hash: str
    r2_parent_source_run_id: str
    r2_parent_source_step: int
    r2_parent_proposal_index: int
    r2_parent_source_commit: str
    r2_parent_source_log_sha256: str
    r2_parent_source_summary_sha256: str
    r2_parent_source_config_hash: str
    r2_parent_search_score: float
    r2_l_manual: float
    r2_l_required: float
    r2_effect_source_commit: str
    r2_effect_document_sha256: str
    r2_budget_source_commit: str

    @model_validator(mode="after")
    def validate_r2_contract(self) -> Self:
        """Reject every drift from the frozen R2 cell definition."""

        if self.evaluation_budget != R2_EVALUATION_BUDGET:
            raise ValueError("R2 evaluation_budget is frozen at 400")
        if self.seed not in R2_SEEDS:
            raise ValueError("R2 seed is outside the frozen five-seed matrix")
        if self.run_id != f"{R2_RUN_ID_PREFIX}{self.seed}":
            raise ValueError("R2 run_id does not match its seed")
        if self.anchor_released or self.openems_cross_check_authorized:
            raise ValueError("R2 cannot release or authorize openEMS")
        if self.max_consecutive_rejections != 100:
            raise ValueError("R2 consecutive-rejection limit changed")
        if self.max_total_proposal_attempts != 6000:
            raise ValueError("R2 proposal-attempt limit changed")
        if self.budget_source_summary_sha256 != R2_BUDGET_SUMMARY_SHA256:
            raise ValueError("R2 budget summary provenance changed")
        if self.budget_source_config_hash != R2_BUDGET_CONFIG_HASH:
            raise ValueError("R2 budget config provenance changed")
        if _FULL_COMMIT.fullmatch(self.preregistration_commit) is None:
            raise ValueError("R2 preregistration commit must be full length")
        if self.preregistration_commit != R2_PREREGISTRATION_COMMIT:
            raise ValueError("R2 preregistration commit changed")
        if _FULL_COMMIT.fullmatch(self.execution_commit) is None:
            raise ValueError("R2 execution commit must be full length")
        inherited = (
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
        if any(value is not None for value in inherited):
            raise ValueError("R2 must not carry inherited warm-parent provenance")
        expected: tuple[tuple[object, object], ...] = (
            (self.r2_parent_pair_hash, R2_PARENT_PAIR_HASH),
            (self.r2_parent_hardware_hash, R2_PARENT_HARDWARE_HASH),
            (self.r2_parent_state_a_geometry_hash, R2_PARENT_STATE_A_GEOMETRY_HASH),
            (self.r2_parent_state_b_geometry_hash, R2_PARENT_STATE_B_GEOMETRY_HASH),
            (self.r2_parent_source_run_id, R2_PARENT_SOURCE_RUN_ID),
            (self.r2_parent_source_step, R2_PARENT_SOURCE_STEP),
            (self.r2_parent_proposal_index, R2_PARENT_PROPOSAL_INDEX),
            (self.r2_parent_source_commit, R2_SOURCE_COMMIT),
            (self.r2_parent_source_log_sha256, R2_PARENT_SOURCE_LOG_SHA256),
            (self.r2_parent_source_summary_sha256, R2_PARENT_SOURCE_SUMMARY_SHA256),
            (self.r2_parent_source_config_hash, R2_PARENT_SOURCE_CONFIG_HASH),
            (self.r2_parent_search_score, R2_PARENT_SEARCH_SCORE),
            (self.r2_l_manual, R2_L_MANUAL),
            (self.r2_l_required, R2_L_REQUIRED),
            (self.r2_effect_source_commit, R2_EFFECT_COMMIT),
            (self.r2_effect_document_sha256, R2_EFFECT_DOCUMENT_SHA256),
            (self.r2_budget_source_commit, BUDGET_SOURCE_COMMIT),
        )
        if any(actual != frozen for actual, frozen in expected):
            raise ValueError("R2 frozen provenance or scalar field changed")
        return self


class R2FrozenInputs(BaseModel):
    """Validated evidence available only after all pre-solver gates pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_commit: str
    parent_candidate: FrozenCategoryCandidate
    parent_record: PairedEvaluationRecord
    preflight: PairedPreflightSummary


def _read_exact_blob(
    repo_root: Path,
    commit: str,
    path: Path,
    expected_sha256: str,
    label: str,
) -> bytes:
    try:
        current = (repo_root / path).read_bytes()
    except OSError as error:
        raise PairedBatchError(f"cannot read {label}: {error}") from error
    committed = _git_blob(repo_root, commit, path)
    _require_exact_bytes(current, committed, expected_sha256, label)
    return current


def _validate_clean_code_tree(repo_root: Path) -> None:
    status = _git(
        repo_root,
        "status",
        "--porcelain",
        "--",
        "yaf_ai",
        "scripts",
        "tests",
        "pyproject.toml",
    )
    if status:
        raise PairedBatchError("R2 code tree is not clean at execution HEAD")


def _validate_frozen_code(
    repo_root: Path,
    execution_commit: str,
) -> None:
    _require_ancestor(repo_root, R2_FROZEN_PACKAGE_COMMIT, execution_commit)
    for path, frozen_blob in FROZEN_SCIENCE_BLOBS.items():
        execution_blob = _git(
            repo_root,
            "rev-parse",
            f"{execution_commit}:{path.as_posix()}",
        ).decode("ascii").strip()
        if execution_blob != frozen_blob:
            raise PairedBatchError(f"frozen science blob changed: {path}")
        workspace_blob = _git(
            repo_root,
            "hash-object",
            f"--path={path.as_posix()}",
            path.as_posix(),
        ).decode("ascii").strip()
        if workspace_blob != execution_blob:
            raise PairedBatchError(f"workspace science bytes changed: {path}")
    for path in R2_CODE_PATHS:
        execution_blob = _git(
            repo_root,
            "rev-parse",
            f"{execution_commit}:{path.as_posix()}",
        ).decode("ascii").strip()
        workspace_blob = _git(
            repo_root,
            "hash-object",
            f"--path={path.as_posix()}",
            path.as_posix(),
        ).decode("ascii").strip()
        if workspace_blob != execution_blob:
            raise PairedBatchError(f"R2 code differs from execution commit: {path}")
    _validate_clean_code_tree(repo_root)


def _validate_budget(repo_root: Path) -> PairedPreflightSummary:
    payload = _read_exact_blob(
        repo_root,
        BUDGET_SOURCE_COMMIT,
        BUDGET_SUMMARY_PATH,
        R2_BUDGET_SUMMARY_SHA256,
        "R2 budget-source summary",
    )
    try:
        summary = PairedPreflightSummary.model_validate_json(payload)
    except ValueError as error:
        raise PairedBatchError(f"cannot parse R2 budget evidence: {error}") from error
    if (
        summary.result_status != "completed"
        or summary.raw_budget != 907
        or summary.budget != 300
        or summary.config_hash != R2_BUDGET_CONFIG_HASH
        or summary.t_pair_p95_seconds != 3.7018278000032296
        or summary.p95_method != PREFLIGHT_P95_METHOD
        or summary.parallel_workers != 1
    ):
        raise PairedBatchError("R2 budget-source fields differ from preregistration")
    return summary


def _validate_source_manifest(repo_root: Path) -> None:
    pinned = _git_blob(repo_root, R2_SOURCE_COMMIT, SOURCE_MANIFEST_PATH)
    if _sha256(pinned) != SOURCE_MANIFEST_SHA256:
        raise PairedBatchError("pinned source manifest SHA-256 changed")
    try:
        current = (repo_root / SOURCE_MANIFEST_PATH).read_bytes()
        pinned_entry = _manifest_index(pinned)[R2_PARENT_SOURCE_RUN_ID]
        current_entry = _manifest_index(current)[R2_PARENT_SOURCE_RUN_ID]
    except (OSError, KeyError, ValueError) as error:
        raise PairedBatchError(f"cannot resolve R2 source manifest entry: {error}") from error
    pinned_dump = pinned_entry.model_dump(mode="json")
    current_dump = current_entry.model_dump(mode="json")
    pinned_canonical = _canonical_manifest_entry(pinned_dump)
    current_canonical = _canonical_manifest_entry(current_dump)
    if pinned_canonical != current_canonical:
        raise PairedBatchError("current R2 source manifest entry changed")
    if _sha256(pinned_canonical) != R2_SOURCE_MANIFEST_ENTRY_SHA256:
        raise PairedBatchError("R2 source manifest-entry SHA-256 changed")
    expected = (
        pinned_entry.config_hash == R2_PARENT_SOURCE_CONFIG_HASH,
        pinned_entry.sha256.get("log.jsonl") == R2_PARENT_SOURCE_LOG_SHA256,
        pinned_entry.sha256.get("summary.json") == R2_PARENT_SOURCE_SUMMARY_SHA256,
        pinned_entry.seed == 101,
        pinned_entry.steps_completed == 300,
        pinned_dump.get("overwritten") is False,
    )
    if not all(expected):
        raise PairedBatchError("R2 source manifest fields differ from preregistration")


def _find_parent_record(log_payload: bytes) -> PairedEvaluationRecord:
    try:
        records, _rejected, _indexes, _single, _single_rejected, _sequence = (
            _load_paired_evaluations_bytes(
                log_payload,
                run_id=R2_PARENT_SOURCE_RUN_ID,
                allow_manual_events=False,
            )
        )
    except ValueError as error:
        raise PairedBatchError(f"cannot parse R2 parent source log: {error}") from error
    selected = tuple(
        record
        for record in records
        if record.step_index == R2_PARENT_SOURCE_STEP
        and record.proposal_index == R2_PARENT_PROPOSAL_INDEX
    )
    if len(selected) != 1:
        raise PairedBatchError("R2 parent source event is not unique")
    return selected[0]


def _validate_parent_evidence(
    repo_root: Path,
) -> tuple[FrozenCategoryCandidate, PairedEvaluationRecord]:
    log_payload = _read_exact_blob(
        repo_root,
        R2_SOURCE_COMMIT,
        SOURCE_LOG_PATH,
        R2_PARENT_SOURCE_LOG_SHA256,
        "R2 parent source log",
    )
    summary_payload = _read_exact_blob(
        repo_root,
        R2_SOURCE_COMMIT,
        SOURCE_SUMMARY_PATH,
        R2_PARENT_SOURCE_SUMMARY_SHA256,
        "R2 parent source summary",
    )
    effect_payload = _read_exact_blob(
        repo_root,
        R2_EFFECT_COMMIT,
        EFFECT_DOCUMENT_PATH,
        R2_EFFECT_DOCUMENT_SHA256,
        "R2 effect document",
    )
    try:
        source_summary = PairedRunSummary.model_validate_json(summary_payload)
        effect = CandidateFreezeDocument.model_validate_json(effect_payload)
    except ValueError as error:
        raise PairedBatchError(f"cannot parse R2 frozen evidence: {error}") from error
    if (
        source_summary.run_id != R2_PARENT_SOURCE_RUN_ID
        or source_summary.seed != 101
        or source_summary.status != "completed"
        or source_summary.steps_completed != 300
        or source_summary.config_hash != R2_PARENT_SOURCE_CONFIG_HASH
    ):
        raise PairedBatchError("R2 parent source summary fields changed")
    candidates = tuple(
        candidate
        for candidate in effect.candidates
        if candidate.pair_hash == R2_PARENT_PAIR_HASH
    )
    if len(candidates) != 1:
        raise PairedBatchError("R2 parent candidate is not unique")
    candidate = candidates[0]
    record = _find_parent_record(log_payload)
    expected_candidate = (
        candidate.category == "top-es",
        candidate.source_run_id == R2_PARENT_SOURCE_RUN_ID,
        candidate.source_step_index == R2_PARENT_SOURCE_STEP,
        candidate.source_proposal_index == R2_PARENT_PROPOSAL_INDEX,
        candidate.source_log_sha256 == R2_PARENT_SOURCE_LOG_SHA256,
        candidate.source_summary_sha256 == R2_PARENT_SOURCE_SUMMARY_SHA256,
        candidate.hardware_hash == R2_PARENT_HARDWARE_HASH,
        candidate.state_a_geometry_hash == R2_PARENT_STATE_A_GEOMETRY_HASH,
        candidate.state_b_geometry_hash == R2_PARENT_STATE_B_GEOMETRY_HASH,
        candidate.search_score == R2_PARENT_SEARCH_SCORE,
        candidate.metrics.search_score == R2_PARENT_SEARCH_SCORE,
    )
    if not all(expected_candidate):
        raise PairedBatchError("R2 frozen candidate fields changed")
    evaluation = record.evaluation
    if (
        record.run_id != R2_PARENT_SOURCE_RUN_ID
        or record.proposer != "es"
        or record.proposal != candidate.proposal
        or evaluation.pair_hash != R2_PARENT_PAIR_HASH
        or evaluation.hardware_hash != R2_PARENT_HARDWARE_HASH
        or evaluation.state_a_geometry_hash != R2_PARENT_STATE_A_GEOMETRY_HASH
        or evaluation.state_b_geometry_hash != R2_PARENT_STATE_B_GEOMETRY_HASH
        or evaluation.metrics.search_score != R2_PARENT_SEARCH_SCORE
    ):
        raise PairedBatchError("R2 source row differs from the frozen candidate")
    proposal = candidate.proposal
    geometry_a = build_state_geometry(proposal.hardware, proposal.state_a)
    geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
    if (
        pair_hash(proposal) != R2_PARENT_PAIR_HASH
        or hardware_hash(proposal.hardware) != R2_PARENT_HARDWARE_HASH
        or state_geometry_hash(proposal.hardware, proposal.state_a, geometry_a)
        != R2_PARENT_STATE_A_GEOMETRY_HASH
        or state_geometry_hash(proposal.hardware, proposal.state_b, geometry_b)
        != R2_PARENT_STATE_B_GEOMETRY_HASH
    ):
        raise PairedBatchError("R2 parent hashes do not reconstruct")
    encoded = encode_warm_parent(proposal)
    if decode_normalized(encoded.tolist(), "es") != proposal:
        raise PairedBatchError("R2 parent encoding does not round-trip")
    if repr(R2_L_REQUIRED) != "0.19394054289730642":
        raise PairedBatchError("R2 reflected-power threshold representation changed")
    return candidate, record


def load_r2_frozen_inputs(repo_root: Path) -> R2FrozenInputs:
    """Run every immutable evidence gate before constructing a solver."""

    resolved_root = repo_root.resolve()
    execution_commit = _git(resolved_root, "rev-parse", "HEAD").decode().strip()
    if _FULL_COMMIT.fullmatch(execution_commit) is None:
        raise PairedBatchError("R2 execution HEAD is not a full commit hash")
    for ancestor in (
        R2_PREREGISTRATION_COMMIT,
        R2_SOURCE_COMMIT,
        R2_EFFECT_COMMIT,
        BUDGET_SOURCE_COMMIT,
        R2_FROZEN_PACKAGE_COMMIT,
    ):
        _require_ancestor(resolved_root, ancestor, execution_commit)
    _validate_frozen_code(resolved_root, execution_commit)
    _validate_source_manifest(resolved_root)
    preflight = _validate_budget(resolved_root)
    candidate, record = _validate_parent_evidence(resolved_root)
    return R2FrozenInputs(
        execution_commit=execution_commit,
        parent_candidate=candidate,
        parent_record=record,
        preflight=preflight,
    )


def build_r2_config(seed: int, inputs: R2FrozenInputs) -> R2PairedRunConfig:
    """Build one frozen R2 config with no inherited warm-parent fields."""

    return R2PairedRunConfig(
        run_id=f"{R2_RUN_ID_PREFIX}{seed}",
        seed=seed,
        evaluation_budget=R2_EVALUATION_BUDGET,
        anchor_released=False,
        openems_cross_check_authorized=False,
        preregistration_commit=R2_PREREGISTRATION_COMMIT,
        execution_commit=inputs.execution_commit,
        budget_source_summary_sha256=R2_BUDGET_SUMMARY_SHA256,
        budget_source_config_hash=R2_BUDGET_CONFIG_HASH,
        r2_parent_pair_hash=R2_PARENT_PAIR_HASH,
        r2_parent_hardware_hash=R2_PARENT_HARDWARE_HASH,
        r2_parent_state_a_geometry_hash=R2_PARENT_STATE_A_GEOMETRY_HASH,
        r2_parent_state_b_geometry_hash=R2_PARENT_STATE_B_GEOMETRY_HASH,
        r2_parent_source_run_id=R2_PARENT_SOURCE_RUN_ID,
        r2_parent_source_step=R2_PARENT_SOURCE_STEP,
        r2_parent_proposal_index=R2_PARENT_PROPOSAL_INDEX,
        r2_parent_source_commit=R2_SOURCE_COMMIT,
        r2_parent_source_log_sha256=R2_PARENT_SOURCE_LOG_SHA256,
        r2_parent_source_summary_sha256=R2_PARENT_SOURCE_SUMMARY_SHA256,
        r2_parent_source_config_hash=R2_PARENT_SOURCE_CONFIG_HASH,
        r2_parent_search_score=R2_PARENT_SEARCH_SCORE,
        r2_l_manual=R2_L_MANUAL,
        r2_l_required=R2_L_REQUIRED,
        r2_effect_source_commit=R2_EFFECT_COMMIT,
        r2_effect_document_sha256=R2_EFFECT_DOCUMENT_SHA256,
        r2_budget_source_commit=BUDGET_SOURCE_COMMIT,
    )


def build_r2_proposer(seed: int, inputs: R2FrozenInputs) -> R2ParentReturnES:
    """Construct the isolated parent-return proposer from frozen evidence."""

    return R2ParentReturnES(
        seed,
        return_parent=inputs.parent_candidate.proposal,
        return_parent_search_score=R2_PARENT_SEARCH_SCORE,
    )


class R2CellResult(BaseModel):
    """One legal terminal plus its independently replayed restart count."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: PairedRunSummary
    restart_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        config = R2PairedRunConfig.model_validate(self.summary.config)
        if (
            self.summary.status
            not in {"completed", "insufficient_feasible_proposals"}
            or self.summary.seed not in R2_SEEDS
            or self.summary.run_id
            != f"{R2_RUN_ID_PREFIX}{self.summary.seed}"
            or config.run_id != self.summary.run_id
            or config.seed != self.summary.seed
            or self.summary.config_hash != _config_hash(config)
            or self.summary.evaluation_budget != R2_EVALUATION_BUDGET
        ):
            raise ValueError("R2 confirmed result is not a frozen legal terminal")
        return self


class R2MatrixError(PairedBatchError):
    """Structured abort preserving the failed seed and confirmed prior cells."""

    def __init__(
        self,
        cause: BaseException,
        *,
        failed_seed: int | None,
        failed_seed_started: bool,
        confirmed_results: tuple[R2CellResult, ...],
    ) -> None:
        if failed_seed is None:
            if failed_seed_started or confirmed_results:
                raise ValueError(
                    "a pre-matrix R2 failure cannot carry a started seed or results"
                )
        else:
            if failed_seed not in R2_SEEDS:
                raise ValueError("R2 matrix error names an unfrozen seed")
            failed_index = R2_SEEDS.index(failed_seed)
            expected_prefix = R2_SEEDS[:failed_index]
            observed_prefix = tuple(
                result.summary.seed for result in confirmed_results
            )
            if observed_prefix != expected_prefix:
                raise ValueError(
                    "R2 confirmed results are not the exact prefix before the failed seed"
                )
            for expected_seed, result in zip(
                expected_prefix,
                confirmed_results,
                strict=True,
            ):
                if (
                    result.summary.run_id
                    != f"{R2_RUN_ID_PREFIX}{expected_seed}"
                    or result.summary.status
                    not in {"completed", "insufficient_feasible_proposals"}
                ):
                    raise ValueError("R2 confirmed result identity or status changed")
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.failed_seed = failed_seed
        self.failed_seed_started = failed_seed_started
        self.confirmed_results = confirmed_results
        self.cause_type = type(cause).__name__
        self.cause_message = str(cause) or "<no message>"


def _replayed_restart_count(
    log_path: Path,
    seed: int,
    inputs: R2FrozenInputs,
) -> int:
    events = _load_paired_events(log_path)
    first = build_r2_proposer(seed, inputs)
    second = build_r2_proposer(seed, inputs)
    _replay_proposer(first, events)
    _replay_proposer(second, events)
    if first.restart_count != second.restart_count:
        raise PairedBatchError("independent R2 terminal replays disagree")
    return first.restart_count


async def run_r2_matrix(
    repo_root: Path,
    *,
    solver_factory: Callable[[], PairedSolver] = PairedNEC2Solver,
) -> tuple[R2CellResult, ...]:
    """Execute or exactly resume the five sequential NEC2-only R2 cells."""

    try:
        inputs = load_r2_frozen_inputs(repo_root)
        os.environ["YAF_NO_FALLBACK"] = "1"
        solver = _StrictSubprocessSolver(solver_factory())
    except Exception as error:
        raise R2MatrixError(
            error,
            failed_seed=None,
            failed_seed_started=False,
            confirmed_results=(),
        ) from error
    runs_root = repo_root.resolve() / "runs"
    results: list[R2CellResult] = []
    for seed in R2_SEEDS:
        try:
            config = build_r2_config(seed, inputs)
            run_directory = runs_root / config.run_id
            existed_terminal = (run_directory / "summary.json").is_file()
            proposer = build_r2_proposer(seed, inputs)
        except Exception as error:
            raise R2MatrixError(
                error,
                failed_seed=seed,
                failed_seed_started=False,
                confirmed_results=tuple(results),
            ) from error
        try:
            summary = await run_paired_adaptive(
                config=config,
                proposer=proposer,
                solver=solver,
                runs_root=runs_root,
            )
            if summary.status not in {"completed", "insufficient_feasible_proposals"}:
                raise PairedBatchError(
                    f"unexpected R2 terminal status for {config.run_id}: {summary.status}"
                )
            replayed = _replayed_restart_count(
                run_directory / "log.jsonl",
                seed,
                inputs,
            )
            if not existed_terminal and proposer.restart_count != replayed:
                raise PairedBatchError("live and replayed R2 restart counts disagree")
            results.append(R2CellResult(summary=summary, restart_count=replayed))
        except Exception as error:
            raise R2MatrixError(
                error,
                failed_seed=seed,
                failed_seed_started=True,
                confirmed_results=tuple(results),
            ) from error
    return tuple(results)
