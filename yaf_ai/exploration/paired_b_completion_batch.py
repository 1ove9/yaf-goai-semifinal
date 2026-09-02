"""Evidence-gated matrix integration for frozen B-parent A-only completion."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.exploration.paired_b_completion_agents import (
    ES_AGENT,
    ES_AGENT_CODE,
    FROZEN_SEEDS,
    RANDOM_AGENT,
    RANDOM_AGENT_CODE,
    RNG_STREAM_REVISION,
    RNG_VERSION,
    STREAM_FORMAT_VERSION,
    AgentName,
    BCompletionRandomProposer,
    BCompletionRestartedES,
    BOnlyParentCodeKey,
    ProposalDecoder,
)
from yaf_ai.exploration.paired_b_completion_coordinates import (
    MAPPING_VERSION,
    decode_a_only_coordinates,
    get_frozen_parent,
)
from yaf_ai.exploration.paired_b_completion_coordinates import (
    FrozenBParent as CoordinateParent,
)
from yaf_ai.exploration.paired_b_completion_gates import (
    FROZEN_PARENTS,
    PREREGISTRATION_COMMIT,
    PREREGISTRATION_DOCUMENT_SHA256,
    RUNTIME_PATHS,
    SOURCE_EVIDENCE_COMMIT,
    SOURCE_MANIFEST_ENTRY_COUNT,
    SOURCE_MANIFEST_SHA256,
    STAGE_B_APPENDIX_SHA256,
    STAGE_B_REPORT_SHA256,
    BCompletionGateInputs,
    canonical_curve_sha256,
    validate_b_completion_source_gates,
)
from yaf_ai.exploration.paired_b_completion_gates import (
    FrozenBParent as SourceParent,
)
from yaf_ai.exploration.paired_feasible_gates import (  # noqa: PLC2701
    BUDGET_CONFIG_HASH,
    BUDGET_SOURCE_COMMIT,
    BUDGET_SUMMARY_SHA256,
    StageAGateError,
    _git,
    _git_blob,
    _require_ancestor,
    _sha256,
)
from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    PairedProposal,
    PairedSolver,
    SearchCurve,
    StateLabel,
    build_state_geometry,
    hardware_hash,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_runner import (  # noqa: PLC2701
    PairedAdaptiveProposer,
    PairedEvaluationRecord,
    PairedRejectionRecord,
    PairedRunConfig,
    PairedRunError,
    PairedRunSummary,
    _config_hash,
    _load_paired_events,
    run_paired_adaptive,
)
from yaf_ai.exploration.paired_solver import PairedNEC2Solver
from yaf_core.domain.geometry import Geometry

STUDY_ID = "semifinal-paired-b-parent-conditional-completion-v1"
SPEC_REVISION = "1.0-b-parent-a-only-exact-support"
EVALUATION_BUDGET = 300
MAX_CONSECUTIVE_REJECTIONS = 100
MAX_TOTAL_PROPOSAL_ATTEMPTS = 300
SOURCE_RUN_ID = "semifinal-paired-stratified-v2-es-s404"
SOURCE_RUN_LOG_SHA256 = "f7039126f8be54ec5d601b13153c80bad067e8f63ef308e04c1d7f803dd5af34"
SOURCE_RUN_SUMMARY_SHA256 = "ceaaa863249a438ecd2224a459b59c1c63d91364980e5b288f79b00b0dabce16"
SOURCE_RUN_CONFIG_HASH = "d51ea414bbedbc7913e28966224d91e786e87a7b896f2b81b3a1340da4c2fedb"
CERTIFICATE_DIRECTORY = Path("artifacts/analysis/semifinal-paired-b-completion-v1-certificate")
CERTIFICATE_SUMMARY_PATH = CERTIFICATE_DIRECTORY / "summary.json"
CERTIFICATE_REPORT_PATH = CERTIFICATE_DIRECTORY / "report.md"
MATRIX_FAILURE_PATH = Path(
    "artifacts/analysis/semifinal-paired-b-completion-v1/matrix_failure.json"
)
EXPECTED_CERTIFICATE_SPANS = 480_002
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_GIT_BLOB = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UNKNOWN_SHA256 = "0" * 64

ParentID = Literal["p01", "p02"]


class BCompletionBatchError(RuntimeError):
    """Raised when the frozen matrix cannot continue without a scientific retry."""


class BCompletionStateBReproductionError(BCompletionBatchError):
    """Carry the expected and actual hashes for one fatal B mismatch."""

    def __init__(
        self,
        message: str,
        *,
        expected_hashes: dict[str, str],
        actual_hashes: dict[str, str],
    ) -> None:
        super().__init__(message)
        if expected_hashes.keys() != actual_hashes.keys():
            raise ValueError("B-reproduction hash key sets differ")
        if not expected_hashes or not all(
            _SHA256.fullmatch(value) is not None
            for value in (*expected_hashes.values(), *actual_hashes.values())
        ):
            raise ValueError("B-reproduction evidence is not lowercase SHA-256")
        self.expected_hashes = dict(expected_hashes)
        self.actual_hashes = dict(actual_hashes)


@dataclass(frozen=True)
class BCompletionCell:
    """One fixed-order matrix cell."""

    parent_id: ParentID
    agent: AgentName
    seed: int

    @property
    def run_id(self) -> str:
        arm = "random" if self.agent == RANDOM_AGENT else "es"
        return f"semifinal-paired-b-completion-{self.parent_id}-{arm}-s{self.seed}"


_PARENT_IDS: tuple[ParentID, ...] = ("p01", "p02")
_AGENT_NAMES: tuple[AgentName, ...] = (RANDOM_AGENT, ES_AGENT)
FROZEN_MATRIX = tuple(
    BCompletionCell(parent_id, agent, seed)
    for parent_id in _PARENT_IDS
    for agent in _AGENT_NAMES
    for seed in FROZEN_SEEDS
)


class BCompletionMatrixInputs(BaseModel):
    """Committed certificate plus all source gates needed by every run config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gates: BCompletionGateInputs
    certificate_evidence_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    certificate_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    certificate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    conditional_implementation_blobs: dict[str, str]

    @model_validator(mode="after")
    def validate_certificate_binding(self) -> Self:
        if (
            self.certificate_evidence_commit != self.gates.execution_commit
            or self.conditional_implementation_blobs != self.gates.runtime_path_blobs
        ):
            raise ValueError("matrix inputs are not bound to execution HEAD bytes")
        expected_paths = {path.as_posix() for path in RUNTIME_PATHS}
        if set(self.conditional_implementation_blobs) != expected_paths or not all(
            _GIT_BLOB.fullmatch(value) is not None
            for value in self.conditional_implementation_blobs.values()
        ):
            raise ValueError("conditional implementation blob map changed")
        return self


class BCompletionRunConfig(PairedRunConfig):
    """One immutable parent-bound cell definition entering the config hash."""

    agent: AgentName  # type: ignore[assignment]
    execution_commit: str
    study_id: str
    spec_revision: str
    mapping_version: str
    rng_version: str
    stream_format_version: str
    rng_stream_revision: int
    agent_code: int
    parent_id: ParentID
    parent_code: int
    bound_parent: SourceParent
    source_evidence_commit: str
    source_manifest_sha256: str
    source_manifest_entry_count: int
    stage_b_appendix_sha256: str
    stage_b_report_sha256: str
    source_run_id: str
    source_run_log_sha256: str
    source_run_summary_sha256: str
    source_run_config_hash: str
    preregistration_document_sha256: str
    implementation_commit: str
    certificate_evidence_commit: str
    certificate_summary_sha256: str
    certificate_report_sha256: str
    budget_source_commit: str
    conditional_implementation_blobs: dict[str, str]
    frozen_science_blobs: dict[str, str]

    @model_validator(mode="after")
    def validate_completion_cell(self) -> Self:
        expected_parent = FROZEN_PARENTS[0 if self.parent_id == "p01" else 1]
        expected_agent_code = RANDOM_AGENT_CODE if self.agent == RANDOM_AGENT else ES_AGENT_CODE
        if (
            self.run_id != BCompletionCell(self.parent_id, self.agent, self.seed).run_id
            or self.seed not in FROZEN_SEEDS
        ):
            raise ValueError("B-completion matrix identity changed")
        if self.parent_code != (1 if self.parent_id == "p01" else 2):
            raise ValueError("B-completion parent code changed")
        if self.bound_parent != expected_parent:
            raise ValueError("B-completion bound-parent provenance changed")
        if (
            self.evaluation_budget != EVALUATION_BUDGET
            or self.max_consecutive_rejections != MAX_CONSECUTIVE_REJECTIONS
            or self.max_total_proposal_attempts != MAX_TOTAL_PROPOSAL_ATTEMPTS
            or self.anchor_released
            or self.openems_cross_check_authorized
        ):
            raise ValueError("B-completion budget or release contract changed")
        expected: tuple[tuple[object, object], ...] = (
            (self.study_id, STUDY_ID),
            (self.spec_revision, SPEC_REVISION),
            (self.mapping_version, MAPPING_VERSION),
            (self.rng_version, RNG_VERSION),
            (self.stream_format_version, STREAM_FORMAT_VERSION),
            (self.rng_stream_revision, RNG_STREAM_REVISION),
            (self.agent_code, expected_agent_code),
            (self.source_evidence_commit, SOURCE_EVIDENCE_COMMIT),
            (self.source_manifest_sha256, SOURCE_MANIFEST_SHA256),
            (self.source_manifest_entry_count, SOURCE_MANIFEST_ENTRY_COUNT),
            (self.stage_b_appendix_sha256, STAGE_B_APPENDIX_SHA256),
            (self.stage_b_report_sha256, STAGE_B_REPORT_SHA256),
            (self.source_run_id, SOURCE_RUN_ID),
            (self.source_run_log_sha256, SOURCE_RUN_LOG_SHA256),
            (self.source_run_summary_sha256, SOURCE_RUN_SUMMARY_SHA256),
            (self.source_run_config_hash, SOURCE_RUN_CONFIG_HASH),
            (self.preregistration_commit, PREREGISTRATION_COMMIT),
            (
                self.preregistration_document_sha256,
                PREREGISTRATION_DOCUMENT_SHA256,
            ),
            (self.budget_source_commit, BUDGET_SOURCE_COMMIT),
            (self.budget_source_summary_sha256, BUDGET_SUMMARY_SHA256),
            (self.budget_source_config_hash, BUDGET_CONFIG_HASH),
        )
        if any(actual != frozen for actual, frozen in expected):
            raise ValueError("B-completion frozen scalar or provenance changed")
        commits = (
            self.preregistration_commit,
            self.implementation_commit,
            self.certificate_evidence_commit,
            self.execution_commit,
        )
        if any(_FULL_COMMIT.fullmatch(value) is None for value in commits):
            raise ValueError("B-completion commit provenance must use full hashes")
        if self.certificate_evidence_commit != self.execution_commit:
            raise ValueError("certificate and execution commits must be commit 3")
        expected_paths = {path.as_posix() for path in RUNTIME_PATHS}
        if set(self.conditional_implementation_blobs) != expected_paths or not all(
            _GIT_BLOB.fullmatch(value) is not None
            for value in self.conditional_implementation_blobs.values()
        ):
            raise ValueError("B-completion runtime blob map changed")
        if not self.frozen_science_blobs or not all(
            _GIT_BLOB.fullmatch(value) is not None for value in self.frozen_science_blobs.values()
        ):
            raise ValueError("B-completion frozen science map is invalid")
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
            raise ValueError("B-completion cells cannot carry warm-parent provenance")
        return self


class BCompletionCellResult(BaseModel):
    """One completed cell in the frozen matrix prefix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: PairedRunSummary

    @model_validator(mode="after")
    def validate_completed(self) -> Self:
        config = BCompletionRunConfig.model_validate(self.summary.config)
        if (
            self.summary.status != "completed"
            or self.summary.run_id != config.run_id
            or self.summary.seed != config.seed
            or self.summary.config_hash != _config_hash(config)
            or self.summary.steps_completed != EVALUATION_BUDGET
            or self.summary.evaluation_budget != EVALUATION_BUDGET
            or self.summary.rejected_proposals != 0
            or self.summary.proposal_attempts != EVALUATION_BUDGET
            or self.summary.solver_mode_counts != {"subprocess": 2 * EVALUATION_BUDGET}
            or self.summary.termination_reason != "accepted paired-evaluation budget completed"
        ):
            raise ValueError("B-completion result is not the sole legal terminal")
        return self


class MatrixFailureRecord(BaseModel):
    """Atomic terminal marker for one failed fixed-order matrix."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    study_id: Literal["semifinal-paired-b-parent-conditional-completion-v1"] = (
        "semifinal-paired-b-parent-conditional-completion-v1"
    )
    study_status: str = Field(min_length=1)
    failed_run_id: str
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    proposal_attempts: int = Field(ge=0)
    partial_log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    partial_log_bytes: int = Field(ge=0)
    partial_log_lines: int = Field(ge=0)
    exception_class: str = Field(min_length=1)
    exception_message: str = Field(min_length=1)
    expected_b_hashes: dict[str, str] | None = None
    actual_b_hashes: dict[str, str] | None = None
    completed_prefix: tuple[str, ...]

    @model_validator(mode="after")
    def validate_failure(self) -> Self:
        run_ids = tuple(cell.run_id for cell in FROZEN_MATRIX)
        if self.failed_run_id not in run_ids:
            raise ValueError("matrix failure names an unfrozen run")
        index = run_ids.index(self.failed_run_id)
        if self.completed_prefix != run_ids[:index]:
            raise ValueError("matrix failure completed prefix changed")
        if self.accepted_count + self.rejected_count > self.proposal_attempts:
            raise ValueError("matrix failure attempt counts are inconsistent")
        if (self.expected_b_hashes is None) != (self.actual_b_hashes is None):
            raise ValueError("B-reproduction hashes must be recorded together")
        if (
            self.expected_b_hashes is not None
            and self.actual_b_hashes is not None
            and (
                self.expected_b_hashes.keys() != self.actual_b_hashes.keys()
                or not all(
                    _SHA256.fullmatch(value) is not None
                    for value in (
                        *self.expected_b_hashes.values(),
                        *self.actual_b_hashes.values(),
                    )
                )
            )
        ):
            raise ValueError("matrix failure B hashes are invalid")
        return self


class BCompletionMatrixError(BCompletionBatchError):
    """Expose the persisted terminal marker to the CLI without permitting retry."""

    def __init__(self, failure: MatrixFailureRecord) -> None:
        super().__init__(f"{failure.exception_class}: {failure.exception_message}")
        self.failure = failure


def _coordinate_parent(parent_id: ParentID) -> CoordinateParent:
    return get_frozen_parent(parent_id)


def build_parent_decoder(parent_id: ParentID) -> ProposalDecoder:
    """Bind one frozen parent in the sole two-dimensional decoder closure."""

    parent = _coordinate_parent(parent_id)

    def decode(values: tuple[float, float], agent: AgentName) -> PairedProposal:
        return decode_a_only_coordinates(parent, values, agent)

    return decode


def _parent_code_keys(inputs: BCompletionMatrixInputs) -> tuple[BOnlyParentCodeKey, ...]:
    return tuple(
        BOnlyParentCodeKey(
            parent_id=parent.parent_id,
            state_b_geometry_hash=parent.state_b_geometry_hash,
            hardware_hash=parent.hardware_hash,
            run_id=parent.source_run_id,
            step_index=parent.step_index,
            proposal_index=parent.proposal_index,
        )
        for parent in inputs.gates.parents
    )


def build_proposer(
    cell: BCompletionCell,
    inputs: BCompletionMatrixInputs,
) -> PairedAdaptiveProposer:
    """Construct one random or cold-ES proposer over only A length/span."""

    parents = _parent_code_keys(inputs)
    decoder = build_parent_decoder(cell.parent_id)
    if cell.agent == RANDOM_AGENT:
        return BCompletionRandomProposer(
            seed=cell.seed,
            parent_id=cell.parent_id,
            parents=parents,
            decoder=decoder,
        )
    return BCompletionRestartedES(
        seed=cell.seed,
        parent_id=cell.parent_id,
        parents=parents,
        decoder=decoder,
    )


def _source_parent(inputs: BCompletionMatrixInputs, parent_id: ParentID) -> SourceParent:
    matches = tuple(parent for parent in inputs.gates.parents if parent.parent_id == parent_id)
    if len(matches) != 1:
        raise BCompletionBatchError("source gates do not contain one bound parent")
    return matches[0]


def build_run_config(
    cell: BCompletionCell,
    inputs: BCompletionMatrixInputs,
) -> BCompletionRunConfig:
    """Build one immutable config with the complete parent and evidence binding."""

    parent = _source_parent(inputs, cell.parent_id)
    return BCompletionRunConfig(
        run_id=cell.run_id,
        agent=cell.agent,
        agent_code=RANDOM_AGENT_CODE if cell.agent == RANDOM_AGENT else ES_AGENT_CODE,
        seed=cell.seed,
        evaluation_budget=EVALUATION_BUDGET,
        anchor_released=False,
        openems_cross_check_authorized=False,
        preregistration_commit=PREREGISTRATION_COMMIT,
        execution_commit=inputs.gates.execution_commit,
        budget_source_summary_sha256=BUDGET_SUMMARY_SHA256,
        budget_source_config_hash=BUDGET_CONFIG_HASH,
        max_consecutive_rejections=MAX_CONSECUTIVE_REJECTIONS,
        max_total_proposal_attempts=MAX_TOTAL_PROPOSAL_ATTEMPTS,
        study_id=STUDY_ID,
        spec_revision=SPEC_REVISION,
        mapping_version=MAPPING_VERSION,
        rng_version=RNG_VERSION,
        stream_format_version=STREAM_FORMAT_VERSION,
        rng_stream_revision=RNG_STREAM_REVISION,
        parent_id=cell.parent_id,
        parent_code=1 if cell.parent_id == "p01" else 2,
        bound_parent=parent,
        source_evidence_commit=SOURCE_EVIDENCE_COMMIT,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_manifest_entry_count=SOURCE_MANIFEST_ENTRY_COUNT,
        stage_b_appendix_sha256=STAGE_B_APPENDIX_SHA256,
        stage_b_report_sha256=STAGE_B_REPORT_SHA256,
        source_run_id=SOURCE_RUN_ID,
        source_run_log_sha256=SOURCE_RUN_LOG_SHA256,
        source_run_summary_sha256=SOURCE_RUN_SUMMARY_SHA256,
        source_run_config_hash=SOURCE_RUN_CONFIG_HASH,
        preregistration_document_sha256=PREREGISTRATION_DOCUMENT_SHA256,
        implementation_commit=inputs.gates.implementation_commit,
        certificate_evidence_commit=inputs.certificate_evidence_commit,
        certificate_summary_sha256=inputs.certificate_summary_sha256,
        certificate_report_sha256=inputs.certificate_report_sha256,
        budget_source_commit=BUDGET_SOURCE_COMMIT,
        conditional_implementation_blobs=inputs.conditional_implementation_blobs,
        frozen_science_blobs=inputs.gates.frozen_science_blobs,
    )


def _workspace_commit_bytes(root: Path, commit: str, path: Path) -> bytes:
    committed = _git_blob(root, commit, path)
    try:
        workspace = (root / path).read_bytes()
    except OSError as error:
        raise StageAGateError(f"cannot read certificate evidence {path}: {error}") from error
    if committed != workspace:
        raise StageAGateError(f"certificate evidence differs from commit: {path}")
    return committed


def _certificate_object(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StageAGateError(f"cannot parse certificate summary: {error}") from error
    if not isinstance(value, dict):
        raise StageAGateError("certificate summary is not an object")
    return cast(dict[str, Any], value)


def load_matrix_inputs(
    repo_root: Path,
    *,
    implementation_commit: str,
    certificate_evidence_commit: str,
) -> BCompletionMatrixInputs:
    """Validate source gates and the committed pass certificate before a solver."""

    root = repo_root.resolve()
    if _FULL_COMMIT.fullmatch(certificate_evidence_commit) is None:
        raise StageAGateError("certificate evidence commit must be a full hash")
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if head != certificate_evidence_commit:
        raise StageAGateError("certificate evidence commit must equal execution HEAD")
    _require_ancestor(root, implementation_commit, certificate_evidence_commit)
    gates = validate_b_completion_source_gates(
        root,
        implementation_commit,
        certificate_evidence_commit,
    )
    summary_bytes = _workspace_commit_bytes(
        root, certificate_evidence_commit, CERTIFICATE_SUMMARY_PATH
    )
    report_bytes = _workspace_commit_bytes(
        root, certificate_evidence_commit, CERTIFICATE_REPORT_PATH
    )
    summary = _certificate_object(summary_bytes)
    provenance = summary.get("provenance")
    if not isinstance(provenance, dict):
        raise StageAGateError("certificate provenance is not an object")
    certificate = summary.get("certificate")
    if not isinstance(certificate, dict):
        raise StageAGateError("certificate statistics are not an object")
    runtime_map = summary.get("conditional_implementation_blobs")
    if (
        summary.get("study_id") != STUDY_ID
        or summary.get("spec_revision") != SPEC_REVISION
        or summary.get("mapping_version") != MAPPING_VERSION
        or summary.get("status") != "support_certificate_passed"
        or summary.get("expected_span_count") != EXPECTED_CERTIFICATE_SPANS
        or summary.get("checked_span_count") != EXPECTED_CERTIFICATE_SPANS
        or summary.get("failed_span_count") != 0
        or summary.get("solver_calls") != 0
        or summary.get("openems_calls") != 0
        or summary.get("source_evidence_commit") != SOURCE_EVIDENCE_COMMIT
        or summary.get("preregistration_commit") != PREREGISTRATION_COMMIT
        or summary.get("implementation_commit") != implementation_commit
        or certificate.get("status") != "passed"
        or certificate.get("checked_span_count") != EXPECTED_CERTIFICATE_SPANS
        or certificate.get("failed_span_count") != 0
        or provenance.get("implementation_commit") != implementation_commit
        or provenance.get("execution_commit") != implementation_commit
        or runtime_map != gates.runtime_path_blobs
        or provenance.get("runtime_path_blobs") != gates.runtime_path_blobs
    ):
        raise StageAGateError("certificate is not the sole legal pass endpoint")
    return BCompletionMatrixInputs(
        gates=gates,
        certificate_evidence_commit=certificate_evidence_commit,
        certificate_summary_sha256=_sha256(summary_bytes),
        certificate_report_sha256=_sha256(report_bytes),
        conditional_implementation_blobs=gates.runtime_path_blobs,
    )


class ParentBoundStrictSubprocessSolver:
    """Require real NEC2 curves and byte-identical state-B reproduction."""

    def __init__(self, solver: PairedSolver, parent: CoordinateParent) -> None:
        self._solver = solver
        self._parent = parent
        self._geometry_b = build_state_geometry(parent.hardware, parent.state_b)
        self._expected = {
            "hardware_hash": parent.expected_hardware_hash,
            "state_b_geometry_hash": parent.expected_state_b_geometry_hash,
            "state_b_curve_sha256": _source_curve_hash(parent.parent_id),
        }

    async def __call__(
        self,
        geometry: Geometry,
        state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        expected_frequency = STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ
        if frequency_hz != expected_frequency:
            raise BCompletionBatchError("solver changed the frozen frequency table")
        if state == "B" and state_geometry_hash(
            self._parent.hardware,
            self._parent.state_b,
            geometry,
        ) != state_geometry_hash(
            self._parent.hardware,
            self._parent.state_b,
            self._geometry_b,
        ):
            actual = {
                "hardware_hash": self._parent.expected_hardware_hash,
                "state_b_geometry_hash": state_geometry_hash(
                    self._parent.hardware,
                    self._parent.state_b,
                    geometry,
                ),
                "state_b_curve_sha256": _UNKNOWN_SHA256,
            }
            raise BCompletionStateBReproductionError(
                "state-B geometry differs before NEC2",
                expected_hashes=self._expected,
                actual_hashes=actual,
            )
        curve = await self._solver(geometry, state, frequency_hz)
        if (
            curve.solver_name != "nec2"
            or curve.solver_mode != "subprocess"
            or curve.frequency_hz != frequency_hz
            or curve.realized_gain_dbi is not None
        ):
            raise BCompletionBatchError(
                "B-completion requires real gain-free NEC2 subprocess curves"
            )
        if state == "B":
            actual = {
                "hardware_hash": self._parent.expected_hardware_hash,
                "state_b_geometry_hash": self._parent.expected_state_b_geometry_hash,
                "state_b_curve_sha256": canonical_curve_sha256(curve.model_dump(mode="json")),
            }
            if actual != self._expected:
                raise BCompletionStateBReproductionError(
                    "state-B curve differs from the frozen source parent",
                    expected_hashes=self._expected,
                    actual_hashes=actual,
                )
        return curve


def _source_curve_hash(parent_id: ParentID) -> str:
    source = FROZEN_PARENTS[0 if parent_id == "p01" else 1]
    return source.state_b_curve_sha256


def _validate_persisted_log(
    path: Path,
    config: BCompletionRunConfig,
    parent: CoordinateParent,
) -> int:
    if not path.is_file():
        return 0
    events = _load_paired_events(path)
    accepted_count = 0
    for event in events:
        if isinstance(event, PairedRejectionRecord):
            raise BCompletionBatchError("persisted prefix contains a fatal rejection")
        if not isinstance(event, PairedEvaluationRecord):
            raise BCompletionBatchError("persisted prefix contains an unknown event")
        evaluation = event.evaluation
        if event.step_index != accepted_count or event.proposal_index != accepted_count:
            raise BCompletionBatchError(
                "persisted accepted indices are not the exact zero-based prefix"
            )
        curve_hash = canonical_curve_sha256(evaluation.state_b_curve.model_dump(mode="json"))
        geometry_b = build_state_geometry(event.proposal.hardware, event.proposal.state_b)
        if (
            event.run_id != config.run_id
            or event.proposer != config.agent
            or event.proposal.proposer != config.agent
            or event.proposal.hardware != parent.hardware
            or event.proposal.state_b != parent.state_b
            or evaluation.hardware_hash != parent.expected_hardware_hash
            or hardware_hash(event.proposal.hardware) != parent.expected_hardware_hash
            or evaluation.state_b_geometry_hash != parent.expected_state_b_geometry_hash
            or state_geometry_hash(event.proposal.hardware, event.proposal.state_b, geometry_b)
            != parent.expected_state_b_geometry_hash
            or curve_hash != _source_curve_hash(config.parent_id)
            or evaluation.state_a_curve.solver_name != "nec2"
            or evaluation.state_b_curve.solver_name != "nec2"
            or evaluation.state_a_curve.solver_mode != "subprocess"
            or evaluation.state_b_curve.solver_mode != "subprocess"
        ):
            raise BCompletionBatchError(
                "persisted accepted prefix changed parent or subprocess evidence"
            )
        accepted_count += 1
    return accepted_count


def _load_completed_summary(path: Path, config: BCompletionRunConfig) -> PairedRunSummary:
    try:
        summary = PairedRunSummary.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise BCompletionBatchError(f"cannot validate completed prefix: {error}") from error
    result = BCompletionCellResult(summary=summary)
    if result.summary.config != config.model_dump(mode="json"):
        raise BCompletionBatchError("completed prefix config bytes changed")
    return result.summary


def _validate_exact_resume(
    runs_root: Path,
    configs: Sequence[BCompletionRunConfig],
) -> tuple[PairedRunSummary, ...]:
    completed: list[PairedRunSummary] = []
    first_incomplete: int | None = None
    for index, config in enumerate(configs):
        directory = runs_root / config.run_id
        summary_path = directory / "summary.json"
        payload_exists = directory.is_dir() and any(directory.iterdir())
        if summary_path.is_file():
            if first_incomplete is not None:
                raise BCompletionBatchError(
                    "persisted matrix terminals are not one fixed-order prefix"
                )
            accepted_count = _validate_persisted_log(
                directory / "log.jsonl", config, _coordinate_parent(config.parent_id)
            )
            if accepted_count != EVALUATION_BUDGET:
                raise BCompletionBatchError(
                    "completed prefix log does not contain exactly 300 accepted rows"
                )
            completed.append(_load_completed_summary(summary_path, config))
        else:
            if first_incomplete is None:
                first_incomplete = index
                _validate_persisted_log(
                    directory / "log.jsonl",
                    config,
                    _coordinate_parent(config.parent_id),
                )
            elif payload_exists:
                raise BCompletionBatchError("a later matrix cell contains evidence before its turn")
    return tuple(completed)


def _partial_diagnostics(run_directory: Path) -> tuple[int, int, int, str, int, int]:
    log_path = run_directory / "log.jsonl"
    try:
        payload = log_path.read_bytes() if log_path.is_file() else b""
    except OSError:
        payload = b""
    accepted = 0
    rejected = 0
    attempts = 0
    try:
        for event in _load_paired_events(log_path) if log_path.is_file() else ():
            attempts += 1
            if isinstance(event, PairedEvaluationRecord):
                accepted += 1
            else:
                rejected += 1
    except PairedRunError:
        attempts = accepted + rejected
    return (
        accepted,
        rejected,
        attempts,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        payload.count(b"\n"),
    )


def _atomic_write_failure(path: Path, failure: MatrixFailureRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            failure.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if b"\r" in payload:
        raise BCompletionBatchError("matrix failure evidence must be LF-only")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _failure_record(
    cell: BCompletionCell,
    error: BaseException,
    *,
    runs_root: Path,
    completed_prefix: Sequence[PairedRunSummary],
) -> MatrixFailureRecord:
    accepted, rejected, attempts, digest, byte_count, line_count = _partial_diagnostics(
        runs_root / cell.run_id
    )
    expected: dict[str, str] | None = None
    actual: dict[str, str] | None = None
    status = "matrix_execution_failed"
    if isinstance(error, BCompletionStateBReproductionError):
        expected = error.expected_hashes
        actual = error.actual_hashes
        status = "state_b_reproduction_failed"
    return MatrixFailureRecord(
        study_status=status,
        failed_run_id=cell.run_id,
        accepted_count=accepted,
        rejected_count=rejected,
        proposal_attempts=attempts,
        partial_log_sha256=digest,
        partial_log_bytes=byte_count,
        partial_log_lines=line_count,
        exception_class=type(error).__name__,
        exception_message=str(error) or "<no message>",
        expected_b_hashes=expected,
        actual_b_hashes=actual,
        completed_prefix=tuple(summary.run_id for summary in completed_prefix),
    )


async def run_b_completion_matrix(
    repo_root: Path,
    *,
    implementation_commit: str,
    certificate_evidence_commit: str,
    solver_factory: Callable[[], PairedSolver] = PairedNEC2Solver,
) -> tuple[BCompletionCellResult, ...]:
    """Execute or exactly resume the twenty parent/agent/seed cells in order."""

    root = repo_root.resolve()
    failure_path = root / MATRIX_FAILURE_PATH
    if failure_path.exists():
        raise BCompletionBatchError("matrix_failure.json is terminal and forbids exact resume")
    inputs = load_matrix_inputs(
        root,
        implementation_commit=implementation_commit,
        certificate_evidence_commit=certificate_evidence_commit,
    )
    configs = tuple(build_run_config(cell, inputs) for cell in FROZEN_MATRIX)
    runs_root = root / "runs"
    completed = list(_validate_exact_resume(runs_root, configs))
    os.environ["YAF_NO_FALLBACK"] = "1"
    base_solver: PairedSolver | None = None
    for index, (cell, config) in enumerate(zip(FROZEN_MATRIX, configs, strict=True)):
        if index < len(completed):
            continue
        try:
            if base_solver is None:
                base_solver = solver_factory()
            proposer = build_proposer(cell, inputs)
            solver = ParentBoundStrictSubprocessSolver(
                base_solver, _coordinate_parent(cell.parent_id)
            )
            summary = await run_paired_adaptive(
                config=config,
                proposer=proposer,
                solver=solver,
                runs_root=runs_root,
            )
            accepted_count = _validate_persisted_log(
                runs_root / cell.run_id / "log.jsonl",
                config,
                _coordinate_parent(cell.parent_id),
            )
            if accepted_count != EVALUATION_BUDGET:
                raise BCompletionBatchError(
                    "completed run log does not contain exactly 300 accepted rows"
                )
            result = BCompletionCellResult(summary=summary)
            completed.append(result.summary)
        except Exception as error:
            failure = _failure_record(
                cell,
                error,
                runs_root=runs_root,
                completed_prefix=completed,
            )
            _atomic_write_failure(failure_path, failure)
            raise BCompletionMatrixError(failure) from error
    return tuple(BCompletionCellResult(summary=summary) for summary in completed)
