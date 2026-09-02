"""Evidence-gated Stage-B matrix for the exact-support stratified study."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, model_validator

from yaf_ai.analysis.paired_feasible_stage_a import StageASummary, render_report
from yaf_ai.exploration.paired_batch import (  # noqa: PLC2701
    PairedBatchError,
    _StrictSubprocessSolver,
)
from yaf_ai.exploration.paired_feasible_agents import (
    StratifiedAgentDiagnostics,
    StratifiedProposer,
    StratifiedRandomProposer,
    StratifiedRestartedES,
)
from yaf_ai.exploration.paired_feasible_gates import (  # noqa: PLC2701
    BUDGET_CONFIG_HASH,
    BUDGET_SOURCE_COMMIT,
    BUDGET_SUMMARY_SHA256,
    FROZEN_SCIENCE_BLOBS,
    R2_APPENDIX_SHA256,
    R2_REPORT_SHA256,
    SOURCE_COMMIT,
    SOURCE_MANIFEST_ENTRY_COUNT,
    SOURCE_MANIFEST_SHA256,
    V1_PREREGISTRATION_COMMIT,
    V1_PREREGISTRATION_DOCUMENT_SHA256,
    StageAGateError,
    _git,
    _git_blob,
    _require_ancestor,
    _sha256,
    _validate_budget,
    _validate_clean_code_tree,
    _validate_frozen_science,
    _validate_manifest,
    _validate_r2_run_files,
)
from yaf_ai.exploration.paired_meander import (
    MANUAL_TURN_COUNTS,
    PairedEvaluation,
    PairedMeanderError,
    PairedProposal,
    PairedSolver,
)
from yaf_ai.exploration.paired_runner import (
    PairedRunConfig,
    PairedRunSummary,
    _config_hash,
    _load_paired_events,
    _replay_proposer,
    run_paired_adaptive,
)
from yaf_ai.exploration.paired_solver import PairedNEC2Solver

STUDY_ID = "semifinal-paired-feasibility-stratified-exact-v2"
SPEC_REVISION = "2.0-exact-nominal-support"
V2_PREREGISTRATION_COMMIT = "e5fab578288f9660a80fa7211b130b5c2fdd63bb"
V2_PREREGISTRATION_DOCUMENT_SHA256 = (
    "b56890d5272a37afc805ef627d6dd37ab1aa47ac46d99e3812bdf190da735a27"
)
V1_PREREGISTRATION_PATH = Path(
    "docs/semifinal-feasibility-stratified-study-preregistration.md"
)
V2_PREREGISTRATION_PATH = Path(
    "docs/semifinal-feasibility-stratified-exact-v2-preregistration.md"
)
STAGE_A_SUMMARY_PATH = Path(
    "artifacts/analysis/semifinal-feasibility-stratified-v2-stage-a/summary.json"
)
STAGE_A_REPORT_PATH = Path(
    "artifacts/analysis/semifinal-feasibility-stratified-v2-stage-a/report.md"
)

RANDOM_AGENT: Literal["random-stratified-v2"] = "random-stratified-v2"
ES_AGENT: Literal["es-stratified-v2"] = "es-stratified-v2"
StageBAgent = Literal["random-stratified-v2", "es-stratified-v2"]
SEEDS = (101, 202, 303, 404, 505)
AGENTS: tuple[StageBAgent, ...] = (RANDOM_AGENT, ES_AGENT)
MATRIX = tuple((agent, seed) for agent in AGENTS for seed in SEEDS)
TURN_ORDER = MANUAL_TURN_COUNTS
QUOTA_PER_TURN = 150
EVALUATION_BUDGET = 600
MAX_CONSECUTIVE_REJECTIONS = 100
MAX_TOTAL_PROPOSAL_ATTEMPTS = 9000
SCHEDULER_VERSION = "fixed-round-robin-by-accepted-count-v1"
RNG_VERSION = "numpy-pcg64-seedsequence-v1"
MAPPING_VERSION = "conditional-exact-feasible-turn-v2"
STREAM_FORMAT_VERSION = "canonical-json-float-hex-lf-v1"
PARENT_MODE = "cold-per-stratum"
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")

IMPLEMENTATION_PATHS = (
    Path("yaf_ai/exploration/paired_feasible_coordinates.py"),
    Path("yaf_ai/exploration/paired_feasible_agents.py"),
    Path("yaf_ai/exploration/paired_feasible_gates.py"),
    Path("yaf_ai/analysis/paired_feasible_stage_a.py"),
    Path("scripts/paired_feasible_stage_a.py"),
    Path("yaf_ai/exploration/paired_feasible_batch.py"),
    Path("scripts/paired_feasible_batch.py"),
    Path("yaf_ai/analysis/paired_feasible_stage_b.py"),
    Path("scripts/paired_feasible_stage_b_report.py"),
)


def _run_id(agent: StageBAgent, seed: int) -> str:
    arm = "random" if agent == RANDOM_AGENT else "es"
    return f"semifinal-paired-stratified-v2-{arm}-s{seed}"


class StageBRunConfig(PairedRunConfig):
    """Immutable exact-v2 cell definition entering the config hash."""

    agent: StageBAgent  # type: ignore[assignment]
    execution_commit: str
    study_id: str
    spec_revision: str
    agent_code: int
    turn_order: tuple[int, ...]
    quota_per_turn: int
    scheduler_version: str
    rng_version: str
    mapping_version: str
    stream_format_version: str
    parent_mode: str
    superseded_v1_preregistration_commit: str
    superseded_v1_preregistration_document_sha256: str
    v2_preregistration_commit: str
    v2_preregistration_document_sha256: str
    implementation_commit: str
    stage_a_evidence_commit: str
    stage_a_summary_sha256: str
    stage_a_report_sha256: str
    source_commit: str
    source_manifest_sha256: str
    source_manifest_entry_count: int
    r2_appendix_sha256: str
    r2_report_sha256: str
    budget_source_commit: str
    frozen_science_blobs: dict[str, str]

    @model_validator(mode="after")
    def validate_stage_b(self) -> Self:
        expected_code = 1 if self.agent == RANDOM_AGENT else 2
        if self.seed not in SEEDS or self.run_id != _run_id(self.agent, self.seed):
            raise ValueError("Stage-B run identity changed")
        if (
            self.evaluation_budget != EVALUATION_BUDGET
            or self.quota_per_turn != QUOTA_PER_TURN
            or self.turn_order != TURN_ORDER
            or self.max_consecutive_rejections != MAX_CONSECUTIVE_REJECTIONS
            or self.max_total_proposal_attempts != MAX_TOTAL_PROPOSAL_ATTEMPTS
        ):
            raise ValueError("Stage-B quota or attempt contract changed")
        if self.anchor_released or self.openems_cross_check_authorized:
            raise ValueError("Stage B cannot release or authorize openEMS")
        expected: tuple[tuple[object, object], ...] = (
            (self.study_id, STUDY_ID),
            (self.spec_revision, SPEC_REVISION),
            (self.agent_code, expected_code),
            (self.scheduler_version, SCHEDULER_VERSION),
            (self.rng_version, RNG_VERSION),
            (self.mapping_version, MAPPING_VERSION),
            (self.stream_format_version, STREAM_FORMAT_VERSION),
            (self.parent_mode, PARENT_MODE),
            (self.superseded_v1_preregistration_commit, V1_PREREGISTRATION_COMMIT),
            (
                self.superseded_v1_preregistration_document_sha256,
                V1_PREREGISTRATION_DOCUMENT_SHA256,
            ),
            (self.v2_preregistration_commit, V2_PREREGISTRATION_COMMIT),
            (
                self.v2_preregistration_document_sha256,
                V2_PREREGISTRATION_DOCUMENT_SHA256,
            ),
            (self.source_commit, SOURCE_COMMIT),
            (self.source_manifest_sha256, SOURCE_MANIFEST_SHA256),
            (self.source_manifest_entry_count, SOURCE_MANIFEST_ENTRY_COUNT),
            (self.r2_appendix_sha256, R2_APPENDIX_SHA256),
            (self.r2_report_sha256, R2_REPORT_SHA256),
            (self.budget_source_commit, BUDGET_SOURCE_COMMIT),
            (self.budget_source_summary_sha256, BUDGET_SUMMARY_SHA256),
            (self.budget_source_config_hash, BUDGET_CONFIG_HASH),
            (
                self.frozen_science_blobs,
                {path.as_posix(): blob for path, blob in FROZEN_SCIENCE_BLOBS.items()},
            ),
        )
        if any(actual != frozen for actual, frozen in expected):
            raise ValueError("Stage-B frozen scalar or provenance changed")
        commits = (
            self.preregistration_commit,
            self.execution_commit,
            self.implementation_commit,
            self.stage_a_evidence_commit,
        )
        if any(_FULL_COMMIT.fullmatch(value) is None for value in commits):
            raise ValueError("Stage-B commit provenance must use full hashes")
        if self.preregistration_commit != V2_PREREGISTRATION_COMMIT:
            raise ValueError("Stage-B preregistration commit changed")
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
            raise ValueError("Stage B must not carry warm-parent provenance")
        return self


class StageBFrozenInputs(BaseModel):
    """Validated committed inputs available before solver construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_commit: str
    implementation_commit: str
    stage_a_evidence_commit: str
    stage_a_summary_sha256: str
    stage_a_report_sha256: str


def _committed_workspace_bytes(root: Path, commit: str, path: Path) -> bytes:
    committed = _git_blob(root, commit, path)
    try:
        workspace = (root / path).read_bytes()
    except OSError as error:
        raise StageAGateError(f"cannot read Stage-A evidence {path}: {error}") from error
    if workspace != committed:
        raise StageAGateError(f"Stage-A workspace evidence differs from {commit}: {path}")
    return committed


def _validate_preregistration(root: Path, commit: str, path: Path, digest: str) -> None:
    payload = _committed_workspace_bytes(root, commit, path)
    if _sha256(payload) != digest:
        raise StageAGateError(f"preregistration document SHA-256 changed: {path}")


def _validate_implementation(root: Path, implementation: str, execution: str) -> None:
    _require_ancestor(root, implementation, execution)
    for path in IMPLEMENTATION_PATHS:
        committed = _git(root, "rev-parse", f"{implementation}:{path.as_posix()}").decode().strip()
        execution_blob = _git(root, "rev-parse", f"{execution}:{path.as_posix()}").decode().strip()
        workspace_blob = _git(
            root,
            "hash-object",
            f"--path={path.as_posix()}",
            path.as_posix(),
        ).decode().strip()
        if committed != execution_blob or execution_blob != workspace_blob:
            raise StageAGateError(f"Stage-B implementation bytes changed: {path}")


def load_stage_b_inputs(root: Path, stage_a_evidence_commit: str) -> StageBFrozenInputs:
    """Validate every committed gate before a solver object can be built."""

    repo = root.resolve()
    if _FULL_COMMIT.fullmatch(stage_a_evidence_commit) is None:
        raise StageAGateError("stage_a_evidence_commit must be a full hash")
    execution = _git(repo, "rev-parse", "HEAD").decode().strip()
    if _FULL_COMMIT.fullmatch(execution) is None:
        raise StageAGateError("execution HEAD is not a full commit hash")
    for ancestor in (
        SOURCE_COMMIT,
        BUDGET_SOURCE_COMMIT,
        V1_PREREGISTRATION_COMMIT,
        V2_PREREGISTRATION_COMMIT,
        stage_a_evidence_commit,
    ):
        _require_ancestor(repo, ancestor, execution)
    _validate_preregistration(
        repo,
        V1_PREREGISTRATION_COMMIT,
        V1_PREREGISTRATION_PATH,
        V1_PREREGISTRATION_DOCUMENT_SHA256,
    )
    _validate_preregistration(
        repo,
        V2_PREREGISTRATION_COMMIT,
        V2_PREREGISTRATION_PATH,
        V2_PREREGISTRATION_DOCUMENT_SHA256,
    )
    summary_payload = _committed_workspace_bytes(
        repo, stage_a_evidence_commit, STAGE_A_SUMMARY_PATH
    )
    report_payload = _committed_workspace_bytes(
        repo, stage_a_evidence_commit, STAGE_A_REPORT_PATH
    )
    try:
        summary = StageASummary.model_validate_json(summary_payload)
    except ValueError as error:
        raise StageAGateError(f"cannot validate Stage-A summary: {error}") from error
    provenance = summary.provenance
    if (
        summary.status != "completed"
        or summary.study_id != STUDY_ID
        or summary.cell_count != 20
        or summary.raw_draws_per_cell != 10_000
        or summary.solver_calls != 0
        or provenance is None
        or provenance.v2_preregistration_commit != V2_PREREGISTRATION_COMMIT
        or provenance.source_commit != SOURCE_COMMIT
        or not provenance.clean_code_tree
    ):
        raise StageAGateError("Stage-A summary is not the sole legal v2 endpoint")
    expected_report = render_report(summary).encode("utf-8")
    if report_payload != expected_report:
        raise StageAGateError("Stage-A report does not reconstruct from its summary")
    implementation = provenance.implementation_commit
    if _FULL_COMMIT.fullmatch(implementation) is None:
        raise StageAGateError("Stage-A implementation commit is not full length")
    _require_ancestor(repo, implementation, stage_a_evidence_commit)
    _validate_manifest(repo)
    _validate_r2_run_files(repo)
    _validate_budget(repo)
    _validate_frozen_science(repo, execution)
    _validate_implementation(repo, implementation, execution)
    _validate_clean_code_tree(repo)
    return StageBFrozenInputs(
        execution_commit=execution,
        implementation_commit=implementation,
        stage_a_evidence_commit=stage_a_evidence_commit,
        stage_a_summary_sha256=_sha256(summary_payload),
        stage_a_report_sha256=_sha256(report_payload),
    )


def build_stage_b_config(
    agent: StageBAgent,
    seed: int,
    inputs: StageBFrozenInputs,
) -> StageBRunConfig:
    """Build one immutable Stage-B cell config."""

    return StageBRunConfig(
        run_id=_run_id(agent, seed),
        agent=agent,
        agent_code=1 if agent == RANDOM_AGENT else 2,
        seed=seed,
        evaluation_budget=EVALUATION_BUDGET,
        anchor_released=False,
        openems_cross_check_authorized=False,
        preregistration_commit=V2_PREREGISTRATION_COMMIT,
        execution_commit=inputs.execution_commit,
        budget_source_summary_sha256=BUDGET_SUMMARY_SHA256,
        budget_source_config_hash=BUDGET_CONFIG_HASH,
        max_consecutive_rejections=MAX_CONSECUTIVE_REJECTIONS,
        max_total_proposal_attempts=MAX_TOTAL_PROPOSAL_ATTEMPTS,
        study_id=STUDY_ID,
        spec_revision=SPEC_REVISION,
        turn_order=TURN_ORDER,
        quota_per_turn=QUOTA_PER_TURN,
        scheduler_version=SCHEDULER_VERSION,
        rng_version=RNG_VERSION,
        mapping_version=MAPPING_VERSION,
        stream_format_version=STREAM_FORMAT_VERSION,
        parent_mode=PARENT_MODE,
        superseded_v1_preregistration_commit=V1_PREREGISTRATION_COMMIT,
        superseded_v1_preregistration_document_sha256=(
            V1_PREREGISTRATION_DOCUMENT_SHA256
        ),
        v2_preregistration_commit=V2_PREREGISTRATION_COMMIT,
        v2_preregistration_document_sha256=V2_PREREGISTRATION_DOCUMENT_SHA256,
        implementation_commit=inputs.implementation_commit,
        stage_a_evidence_commit=inputs.stage_a_evidence_commit,
        stage_a_summary_sha256=inputs.stage_a_summary_sha256,
        stage_a_report_sha256=inputs.stage_a_report_sha256,
        source_commit=SOURCE_COMMIT,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_manifest_entry_count=SOURCE_MANIFEST_ENTRY_COUNT,
        r2_appendix_sha256=R2_APPENDIX_SHA256,
        r2_report_sha256=R2_REPORT_SHA256,
        budget_source_commit=BUDGET_SOURCE_COMMIT,
        frozen_science_blobs={
            path.as_posix(): blob for path, blob in FROZEN_SCIENCE_BLOBS.items()
        },
    )


class _V2ProposerAdapter:
    """Expose v2 labels while reusing the frozen stratified algorithm."""

    def __init__(self, agent: StageBAgent, seed: int) -> None:
        self.agent = agent
        self._delegate: StratifiedProposer = (
            StratifiedRandomProposer(seed)
            if agent == RANDOM_AGENT
            else StratifiedRestartedES(seed)
        )
        self._internal_pending: PairedProposal | None = None
        self._external_pending: PairedProposal | None = None

    @property
    def diagnostics(self) -> StratifiedAgentDiagnostics:
        return self._delegate.diagnostics

    def propose(self) -> PairedProposal:
        internal = self._delegate.propose()
        external = internal.model_copy(update={"proposer": self.agent})
        self._internal_pending = internal
        self._external_pending = external
        return external

    def reject(self, proposal: PairedProposal) -> None:
        if self._external_pending is None or proposal != self._external_pending:
            raise PairedMeanderError("v2 adapter rejection does not match pending proposal")
        if self._internal_pending is None:
            raise PairedMeanderError("v2 adapter internal pending proposal is missing")
        self._delegate.reject(self._internal_pending)
        self._internal_pending = None
        self._external_pending = None

    def observe(self, evaluation: PairedEvaluation) -> None:
        if self._external_pending is None or self._internal_pending is None:
            raise PairedMeanderError("v2 adapter observe called without pending proposal")
        self._delegate.observe(evaluation)
        self._internal_pending = None
        self._external_pending = None


def build_stage_b_proposer(agent: StageBAgent, seed: int) -> _V2ProposerAdapter:
    return _V2ProposerAdapter(agent, seed)


class StageBCellResult(BaseModel):
    """One completed cell and its independently replayed diagnostics."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    summary: PairedRunSummary
    diagnostics: StratifiedAgentDiagnostics

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        config = StageBRunConfig.model_validate(self.summary.config)
        expected_turns = tuple(
            (item.turn_count, item.accepted_count)
            for item in self.diagnostics.islands
        )
        expected_diagnostic_agent = (
            "random-stratified-v1"
            if config.agent == RANDOM_AGENT
            else "es-stratified-v1"
        )
        if (
            self.summary.status != "completed"
            or self.summary.run_id != config.run_id
            or self.summary.seed != config.seed
            or self.summary.config_hash != _config_hash(config)
            or self.summary.steps_completed != EVALUATION_BUDGET
            or self.summary.evaluation_budget != EVALUATION_BUDGET
            or self.summary.termination_reason
            != "accepted paired-evaluation budget completed"
            or self.summary.rejected_proposals != 0
            or self.summary.proposal_attempts != EVALUATION_BUDGET
            or self.summary.solver_mode_counts != {"subprocess": 1_200}
            or self.diagnostics.agent != expected_diagnostic_agent
            or self.diagnostics.accepted_count != EVALUATION_BUDGET
            or expected_turns != ((3, 150), (4, 150), (5, 150), (6, 150))
        ):
            raise ValueError("Stage-B result is not the sole legal completed terminal")
        return self


class StageBMatrixError(PairedBatchError):
    """Structured fail-closed abort with an exact confirmed-cell prefix."""

    def __init__(
        self,
        cause: BaseException,
        *,
        failed_cell: tuple[StageBAgent, int] | None,
        failed_cell_started: bool,
        confirmed_results: tuple[StageBCellResult, ...],
    ) -> None:
        if failed_cell is None:
            if failed_cell_started or confirmed_results:
                raise ValueError("pre-matrix failure cannot carry a started cell or results")
        else:
            if failed_cell not in MATRIX:
                raise ValueError("matrix error names an unfrozen cell")
            index = MATRIX.index(failed_cell)
            observed = tuple(
                (cast(StageBAgent, result.summary.config["agent"]), result.summary.seed)
                for result in confirmed_results
            )
            if observed != MATRIX[:index]:
                raise ValueError("confirmed results are not the exact matrix prefix")
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.failed_cell = failed_cell
        self.failed_cell_started = failed_cell_started
        self.confirmed_results = confirmed_results
        self.cause_type = type(cause).__name__
        self.cause_message = str(cause) or "<no message>"


def _replayed_diagnostics(
    log_path: Path,
    agent: StageBAgent,
    seed: int,
) -> StratifiedAgentDiagnostics:
    events = _load_paired_events(log_path)
    first = build_stage_b_proposer(agent, seed)
    second = build_stage_b_proposer(agent, seed)
    _replay_proposer(first, events)
    _replay_proposer(second, events)
    if first.diagnostics != second.diagnostics:
        raise PairedBatchError("independent Stage-B terminal replays disagree")
    return first.diagnostics


async def run_stage_b_matrix(
    repo_root: Path,
    *,
    stage_a_evidence_commit: str,
    solver_factory: Callable[[], PairedSolver] = PairedNEC2Solver,
) -> tuple[StageBCellResult, ...]:
    """Execute or exactly resume Random five seeds followed by ES five seeds."""

    try:
        inputs = load_stage_b_inputs(repo_root, stage_a_evidence_commit)
        os.environ["YAF_NO_FALLBACK"] = "1"
        solver = _StrictSubprocessSolver(solver_factory())
    except Exception as error:
        raise StageBMatrixError(
            error,
            failed_cell=None,
            failed_cell_started=False,
            confirmed_results=(),
        ) from error
    results: list[StageBCellResult] = []
    runs_root = repo_root.resolve() / "runs"
    for agent, seed in MATRIX:
        try:
            config = build_stage_b_config(agent, seed, inputs)
            run_directory = runs_root / config.run_id
            existed_terminal = (run_directory / "summary.json").is_file()
            proposer = build_stage_b_proposer(agent, seed)
        except Exception as error:
            raise StageBMatrixError(
                error,
                failed_cell=(agent, seed),
                failed_cell_started=False,
                confirmed_results=tuple(results),
            ) from error
        try:
            summary = await run_paired_adaptive(
                config=config,
                proposer=proposer,
                solver=solver,
                runs_root=runs_root,
            )
            replayed = _replayed_diagnostics(run_directory / "log.jsonl", agent, seed)
            if not existed_terminal and proposer.diagnostics != replayed:
                raise PairedBatchError("live and replayed Stage-B diagnostics disagree")
            results.append(StageBCellResult(summary=summary, diagnostics=replayed))
        except Exception as error:
            raise StageBMatrixError(
                error,
                failed_cell=(agent, seed),
                failed_cell_started=True,
                confirmed_results=tuple(results),
            ) from error
    return tuple(results)
