"""Fail-closed provenance gates for the B-parent completion study."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from yaf_ai.exploration.paired_feasible_gates import (
    BUDGET_CONFIG_HASH,
    BUDGET_SOURCE_COMMIT,
    BUDGET_SUMMARY_SHA256,
    StageAGateError,
    _git,
    _git_blob,
    _manifest_entries,
    _manifest_index,
    _require_ancestor,
    _sha256,
    _validate_budget,
)
from yaf_ai.exploration.paired_meander import SearchCurve, score_state_curve

SOURCE_EVIDENCE_COMMIT = "8fb865005791a3f1fa53d212d0f0a1e813f19558"
PREREGISTRATION_COMMIT = "9e9edbc762e8c885052aa08d469e6872b719d79e"
PREREGISTRATION_DOCUMENT_SHA256 = (
    "44136f7116deb284c3b5b9f2fb2a8e3cd67cfd6c3fb0421bf5291db19aa4a26f"
)
SOURCE_MANIFEST_SHA256 = (
    "fb5163a33753b4c8aed50c03e1244c22072be7477a69b234848a7aeaa285c9b2"
)
SOURCE_MANIFEST_ENTRY_COUNT = 234
STAGE_B_APPENDIX_SHA256 = (
    "1513885a474b74cdd7ae9873d642fee698bb4c74e3f9e450c875ccd6f6a690c6"
)
STAGE_B_REPORT_SHA256 = (
    "5911f7eba34653954c7bcb00c8533ff4f47577651cb373754930dc96c9d01d64"
)

MANIFEST_PATH = Path("artifacts/runs/manifest.json")
PREREGISTRATION_PATH = Path(
    "docs/semifinal-paired-b-parent-conditional-completion-preregistration.md"
)
STAGE_B_APPENDIX_PATH = Path(
    "artifacts/analysis/semifinal-feasibility-stratified-v2-stage-b/appendix.json"
)
STAGE_B_REPORT_PATH = Path(
    "artifacts/analysis/semifinal-feasibility-stratified-v2-stage-b/report.md"
)

STAGE_B_RUN_PREFIX = "semifinal-paired-stratified-v2-"
STAGE_B_RUN_IDS = tuple(
    f"semifinal-paired-stratified-v2-{agent}-s{seed}"
    for agent in ("random", "es")
    for seed in (101, 202, 303, 404, 505)
)

RUNTIME_PATHS = (
    Path("yaf_ai/exploration/paired_b_completion_coordinates.py"),
    Path("yaf_ai/exploration/paired_b_completion_agents.py"),
    Path("yaf_ai/exploration/paired_b_completion_gates.py"),
    Path("yaf_ai/exploration/paired_b_completion_batch.py"),
    Path("yaf_ai/analysis/paired_b_completion.py"),
    Path("scripts/paired_b_completion_certificate.py"),
    Path("scripts/paired_b_completion_batch.py"),
    Path("scripts/paired_b_completion_report.py"),
)

FROZEN_SCIENCE_BLOBS: dict[Path, str] = {
    Path("yaf_ai/exploration/paired_meander.py"): (
        "98fd67154d5f6a512fdf46b99da1fc273ba8eced"
    ),
    Path("yaf_ai/exploration/paired_solver.py"): (
        "96efa9fe3e755fbca9b31315d96a330bef7291b9"
    ),
    Path("yaf_ai/exploration/paired_runner.py"): (
        "d2ece9096be6daa86de6b281bb64a8b1150c782e"
    ),
    Path("yaf_ai/exploration/paired_agents.py"): (
        "0b8b8046611bca0fd2e0c0649277e5594f439f99"
    ),
    Path("yaf_ai/exploration/day65_batch.py"): (
        "5944f5c2f9c892aa0a6860b2ef443f914f6baecc"
    ),
    Path("yaf_ai/exploration/paired_feasible_coordinates.py"): (
        "6d120cd8110a95b8d66e036b9c9ed104b247eb5f"
    ),
    Path("yaf_ai/exploration/paired_feasible_agents.py"): (
        "50d885f687285fc516456911602741622e5e5212"
    ),
    Path("yaf_ai/exploration/paired_feasible_batch.py"): (
        "c7d290326e6c80f153e25341d0c456bd2618ea96"
    ),
    Path("yaf_ai/exploration/paired_feasible_gates.py"): (
        "b6f767dc5330ffb6f0edbb3bbf8f72102e1e00a3"
    ),
    Path("yaf_ai/analysis/paired_feasible_stage_b.py"): (
        "080bdbde95917939535526423a74936e56a3dc1f"
    ),
    Path("scripts/paired_feasible_batch.py"): (
        "387306bea448ffbb1fddbe521f1275ec043d4ca9"
    ),
    Path("scripts/paired_feasible_stage_b_report.py"): (
        "cc51df39f4611ad74c92b68abf08189bf31c5d6b"
    ),
}

_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class FrozenBParent(BaseModel):
    """One byte-addressed member of the complete B-valid source set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: Literal["p01", "p02"]
    source_run_id: str
    step_index: int = Field(ge=0)
    proposal_index: int = Field(ge=0)
    raw_line_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_line_bytes: int = Field(gt=0)
    pair_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hardware_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_b_geometry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_b_curve_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_b_total_wire_length_um: int
    state_b_span_ratio_ppm: int
    turn_count: int
    feed_gap_ratio_ppm: int
    terminal_ratio_ppm: int


FROZEN_PARENTS = (
    FrozenBParent(
        parent_id="p01",
        source_run_id="semifinal-paired-stratified-v2-es-s404",
        step_index=52,
        proposal_index=52,
        raw_line_sha256=(
            "14f152d6aa3d817426d2170bd80662b6329b8cf83604084af1308efce65c0fb6"
        ),
        raw_line_bytes=10307,
        pair_hash=(
            "3f197f201833d90efa3d8aea6e9bd1d18cd49e264908f9c34237639c2057dae4"
        ),
        hardware_hash=(
            "52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b"
        ),
        state_b_geometry_hash=(
            "c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1"
        ),
        state_b_curve_sha256=(
            "399b85ea2b8d63faa60743e8534450949bbc9846908c8cdbe995a81794c42181"
        ),
        state_b_total_wire_length_um=26090,
        state_b_span_ratio_ppm=785552,
        turn_count=3,
        feed_gap_ratio_ppm=49001,
        terminal_ratio_ppm=0,
    ),
    FrozenBParent(
        parent_id="p02",
        source_run_id="semifinal-paired-stratified-v2-es-s404",
        step_index=136,
        proposal_index=136,
        raw_line_sha256=(
            "ca216c46bdcc57bc16c2092e29becd42549e7922b6076c4d300177554f12153c"
        ),
        raw_line_bytes=10197,
        pair_hash=(
            "b8180493c7212ca0c8a3165e3aaa26cde542cbc153d01ddb6f009ae9204e8ad3"
        ),
        hardware_hash=(
            "2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1"
        ),
        state_b_geometry_hash=(
            "dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d"
        ),
        state_b_curve_sha256=(
            "f4be9ba23a08b745a1e5f48a0a7bf075eb656a43df0a625a046933886b23b949"
        ),
        state_b_total_wire_length_um=26646,
        state_b_span_ratio_ppm=770570,
        turn_count=3,
        feed_gap_ratio_ppm=48021,
        terminal_ratio_ppm=0,
    ),
)


class BCompletionGateInputs(BaseModel):
    """All immutable inputs proven before certificate or solver construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_evidence_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    preregistration_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    execution_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_entry_count: int
    accepted_record_count: int
    stage_b_run_count: int
    parents: tuple[FrozenBParent, FrozenBParent]
    budget_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    budget_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_science_blobs: dict[str, str]
    runtime_path_blobs: dict[str, str]
    clean_tracked_code: bool


def canonical_curve_sha256(curve_payload: object) -> str:
    """Hash one source curve using the exact preregistered JSON encoding."""

    try:
        payload = json.dumps(
            curve_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise StageAGateError(f"cannot canonicalize state-B curve: {error}") from error
    return hashlib.sha256(payload).hexdigest()


def _workspace_exact(
    root: Path,
    commit: str,
    path: Path,
    expected_sha256: str,
    label: str,
) -> bytes:
    committed = _git_blob(root, commit, path)
    try:
        workspace = (root / path).read_bytes()
    except OSError as error:
        raise StageAGateError(f"cannot read {label}: {error}") from error
    if workspace != committed:
        raise StageAGateError(f"{label} differs from committed evidence")
    if _sha256(committed) != expected_sha256:
        raise StageAGateError(f"{label} SHA-256 differs from preregistration")
    return committed


def _manifest_sha_map(entry: dict[str, object], run_id: str) -> dict[str, str]:
    hashes = entry.get("sha256")
    if not isinstance(hashes, dict):
        raise StageAGateError(f"Stage-B manifest SHA map is invalid: {run_id}")
    result: dict[str, str] = {}
    for filename in ("log.jsonl", "summary.json"):
        digest = hashes.get(filename)
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise StageAGateError(
                f"Stage-B manifest {filename} SHA is invalid: {run_id}"
            )
        result[filename] = digest
    return result


def _json_object(payload: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StageAGateError(f"cannot parse {label}: {error}") from error
    if not isinstance(value, dict):
        raise StageAGateError(f"{label} is not a JSON object")
    return value


def _nested_object(value: object, key: str, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise StageAGateError(f"{label} is not an object")
    child = value.get(key)
    if not isinstance(child, dict):
        raise StageAGateError(f"{label}.{key} is not an object")
    return child


def _integer_field(value: dict[str, object], key: str, label: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool):
        raise StageAGateError(f"{label}.{key} is not an integer")
    return item


def _recomputed_b_valid(event: dict[str, object], label: str) -> tuple[bool, object]:
    evaluation = _nested_object(event, "evaluation", label)
    curve_payload = evaluation.get("state_b_curve")
    try:
        curve = SearchCurve.model_validate(curve_payload)
        recomputed = score_state_curve(curve, "B").valid_search
    except ValueError as error:
        raise StageAGateError(f"cannot validate {label} state-B curve: {error}") from error
    metrics = _nested_object(evaluation, "metrics", f"{label}.evaluation")
    state_b_metrics = _nested_object(metrics, "state_b", f"{label}.evaluation.metrics")
    logged = state_b_metrics.get("valid_search")
    if not isinstance(logged, bool) or logged is not recomputed:
        raise StageAGateError(f"logged state-B validity differs from curve: {label}")
    return recomputed, curve_payload


def _parent_from_event(
    event: dict[str, object],
    raw_line: bytes,
    curve_payload: object,
    parent_id: Literal["p01", "p02"],
    label: str,
) -> FrozenBParent:
    evaluation = _nested_object(event, "evaluation", label)
    proposal = _nested_object(event, "proposal", label)
    hardware = _nested_object(proposal, "hardware", f"{label}.proposal")
    state_b = _nested_object(proposal, "state_b", f"{label}.proposal")
    try:
        return FrozenBParent(
            parent_id=parent_id,
            source_run_id=str(event["run_id"]),
            step_index=_integer_field(event, "step_index", label),
            proposal_index=_integer_field(event, "proposal_index", label),
            raw_line_sha256=_sha256(raw_line),
            raw_line_bytes=len(raw_line),
            pair_hash=str(evaluation["pair_hash"]),
            hardware_hash=str(evaluation["hardware_hash"]),
            state_b_geometry_hash=str(evaluation["state_b_geometry_hash"]),
            state_b_curve_sha256=canonical_curve_sha256(curve_payload),
            state_b_total_wire_length_um=_integer_field(
                state_b, "total_wire_length_um", f"{label}.proposal.state_b"
            ),
            state_b_span_ratio_ppm=_integer_field(
                state_b, "span_ratio_ppm", f"{label}.proposal.state_b"
            ),
            turn_count=_integer_field(
                hardware, "turn_count", f"{label}.proposal.hardware"
            ),
            feed_gap_ratio_ppm=_integer_field(
                hardware, "feed_gap_ratio_ppm", f"{label}.proposal.hardware"
            ),
            terminal_ratio_ppm=_integer_field(
                hardware, "terminal_ratio_ppm", f"{label}.proposal.hardware"
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StageAGateError(f"cannot read frozen parent identity: {label}") from error


def _validate_summary(payload: bytes, run_id: str, manifest_entry: dict[str, object]) -> None:
    summary = _json_object(payload, f"Stage-B summary {run_id}")
    expected = (
        summary.get("run_id") == run_id,
        summary.get("status") == "completed",
        summary.get("steps_completed") == 600,
        summary.get("evaluation_budget") == 600,
        summary.get("rejected_proposals") == 0,
        summary.get("proposal_attempts") == 600,
        summary.get("solver_mode_counts") == {"subprocess": 1200},
        summary.get("config_hash") == manifest_entry.get("config_hash"),
    )
    if not all(expected):
        raise StageAGateError(f"Stage-B summary terminal changed: {run_id}")


def _validate_stage_b_source(
    root: Path,
    source_commit: str,
    source_manifest: list[dict[str, object]],
) -> tuple[tuple[FrozenBParent, FrozenBParent], int]:
    manifest = _manifest_index(source_manifest, "source manifest")
    stage_b_entries = {
        run_id for run_id in manifest if run_id.startswith(STAGE_B_RUN_PREFIX)
    }
    if stage_b_entries != set(STAGE_B_RUN_IDS):
        raise StageAGateError(
            "source manifest does not contain exactly the ten Stage-B entries"
        )
    eligible: list[tuple[dict[str, object], bytes, object, str]] = []
    accepted = 0
    for run_id in STAGE_B_RUN_IDS:
        try:
            entry = manifest[run_id]
        except KeyError as error:
            raise StageAGateError(f"Stage-B manifest entry is missing: {run_id}") from error
        if entry.get("overwritten") is not False:
            raise StageAGateError(f"Stage-B manifest entry was overwritten: {run_id}")
        hashes = _manifest_sha_map(entry, run_id)
        log_path = Path("artifacts/runs") / run_id / "log.jsonl"
        summary_path = Path("artifacts/runs") / run_id / "summary.json"
        log_bytes = _workspace_exact(
            root, source_commit, log_path, hashes["log.jsonl"], f"Stage-B log {run_id}"
        )
        summary_bytes = _workspace_exact(
            root,
            source_commit,
            summary_path,
            hashes["summary.json"],
            f"Stage-B summary {run_id}",
        )
        _validate_summary(summary_bytes, run_id, entry)
        lines = log_bytes.splitlines(keepends=True)
        if len(lines) != 600:
            raise StageAGateError(f"Stage-B log does not contain 600 rows: {run_id}")
        seen_steps: set[int] = set()
        seen_proposals: set[int] = set()
        for line_number, raw_line in enumerate(lines, start=1):
            if not raw_line.endswith(b"\n") or raw_line.endswith(b"\r\n"):
                raise StageAGateError(f"Stage-B log is not LF-only: {run_id}:{line_number}")
            event = _json_object(raw_line, f"Stage-B log {run_id}:{line_number}")
            if event.get("event_type") != "paired_evaluation" or event.get("run_id") != run_id:
                raise StageAGateError(f"Stage-B accepted event identity changed: {run_id}")
            try:
                step = _integer_field(event, "step_index", run_id)
                proposal = _integer_field(event, "proposal_index", run_id)
            except (KeyError, TypeError, ValueError) as error:
                raise StageAGateError(f"Stage-B event index is invalid: {run_id}") from error
            if step in seen_steps or proposal in seen_proposals:
                raise StageAGateError(f"Stage-B event index is duplicated: {run_id}")
            seen_steps.add(step)
            seen_proposals.add(proposal)
            valid, curve_payload = _recomputed_b_valid(
                event, f"Stage-B log {run_id}:{line_number}"
            )
            if valid:
                eligible.append((event, raw_line, curve_payload, run_id))
        if seen_steps != set(range(600)) or seen_proposals != set(range(600)):
            raise StageAGateError(f"Stage-B event indices are not contiguous: {run_id}")
        accepted += len(lines)
    expected_accepted = 600 * len(STAGE_B_RUN_IDS)
    if accepted != expected_accepted or len(eligible) != 2:
        raise StageAGateError("Stage-B B-valid source set is not exactly two of 6000")
    eligible.sort(
        key=lambda item: (
            str(_nested_object(item[0], "evaluation", item[3])["state_b_geometry_hash"]),
            str(_nested_object(item[0], "evaluation", item[3])["hardware_hash"]),
            str(item[0]["run_id"]),
            _integer_field(item[0], "step_index", item[3]),
            _integer_field(item[0], "proposal_index", item[3]),
        )
    )
    actual = tuple(
        _parent_from_event(
            event,
            raw_line,
            curve_payload,
            "p01" if index == 0 else "p02",
            f"eligible source {run_id}",
        )
        for index, (event, raw_line, curve_payload, run_id) in enumerate(eligible)
    )
    if actual != FROZEN_PARENTS:
        raise StageAGateError("Stage-B B-valid source identities changed")
    return (actual[0], actual[1]), accepted


def _validate_frozen_science(
    root: Path,
    implementation_commit: str,
    execution_commit: str,
) -> None:
    for path, expected in FROZEN_SCIENCE_BLOBS.items():
        identities = (
            _git(root, "rev-parse", f"{SOURCE_EVIDENCE_COMMIT}:{path.as_posix()}")
            .decode("ascii")
            .strip(),
            _git(root, "rev-parse", f"{implementation_commit}:{path.as_posix()}")
            .decode("ascii")
            .strip(),
            _git(root, "rev-parse", f"{execution_commit}:{path.as_posix()}")
            .decode("ascii")
            .strip(),
            _git(
                root,
                "hash-object",
                f"--path={path.as_posix()}",
                path.as_posix(),
            )
            .decode("ascii")
            .strip(),
        )
        if any(identity != expected for identity in identities):
            raise StageAGateError(f"frozen science blob changed: {path}")


def _safe_runtime_path(path: Path) -> Path:
    pure = PurePosixPath(path.as_posix())
    if path.is_absolute() or not pure.parts or ".." in pure.parts:
        raise StageAGateError(f"runtime path is not repository-relative: {path}")
    return Path(*pure.parts)


def validate_runtime_path_blobs(
    repo_root: Path,
    implementation_commit: str,
    execution_commit: str,
    runtime_paths: tuple[Path, ...],
) -> dict[str, str]:
    """Require new runtime bytes to match implementation, execution, and workspace."""

    root = repo_root.resolve()
    if _FULL_COMMIT.fullmatch(implementation_commit) is None:
        raise StageAGateError("implementation commit must be a full hash")
    if _FULL_COMMIT.fullmatch(execution_commit) is None:
        raise StageAGateError("execution commit must be a full hash")
    result: dict[str, str] = {}
    for raw_path in runtime_paths:
        path = _safe_runtime_path(raw_path)
        label = path.as_posix()
        if label in result:
            raise StageAGateError(f"runtime path is duplicated: {label}")
        implementation_blob = _git(
            root, "rev-parse", f"{implementation_commit}:{label}"
        ).decode("ascii").strip()
        execution_blob = _git(
            root, "rev-parse", f"{execution_commit}:{label}"
        ).decode("ascii").strip()
        workspace_blob = _git(
            root, "hash-object", f"--path={label}", label
        ).decode("ascii").strip()
        if implementation_blob != execution_blob or execution_blob != workspace_blob:
            raise StageAGateError(f"runtime path bytes changed: {label}")
        result[label] = implementation_blob
    return result


def _validate_clean_tracked_code(root: Path) -> None:
    status = _git(
        root,
        "status",
        "--porcelain",
        "--",
        "yaf_ai",
        "scripts",
        "tests",
        "pyproject.toml",
    )
    if status:
        raise StageAGateError("conditional-completion tracked code tree is not clean")


def validate_b_completion_source_gates(
    repo_root: Path,
    implementation_commit: str,
    execution_commit: str,
    runtime_paths: tuple[Path, ...] = RUNTIME_PATHS,
) -> BCompletionGateInputs:
    """Validate all preregistered inputs before certificate or solver construction."""

    root = repo_root.resolve()
    if runtime_paths != RUNTIME_PATHS:
        raise StageAGateError("conditional runtime path set changed")
    if _FULL_COMMIT.fullmatch(implementation_commit) is None:
        raise StageAGateError("implementation commit must be a full hash")
    if _FULL_COMMIT.fullmatch(execution_commit) is None:
        raise StageAGateError("execution commit must be a full hash")
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if head != execution_commit:
        raise StageAGateError("execution commit must equal HEAD")
    for ancestor in (
        SOURCE_EVIDENCE_COMMIT,
        BUDGET_SOURCE_COMMIT,
        PREREGISTRATION_COMMIT,
        implementation_commit,
    ):
        _require_ancestor(root, ancestor, execution_commit)
    _workspace_exact(
        root,
        PREREGISTRATION_COMMIT,
        PREREGISTRATION_PATH,
        PREREGISTRATION_DOCUMENT_SHA256,
        "conditional-completion preregistration",
    )
    manifest_payload = _workspace_exact(
        root,
        SOURCE_EVIDENCE_COMMIT,
        MANIFEST_PATH,
        SOURCE_MANIFEST_SHA256,
        "234-entry source manifest",
    )
    manifest_entries = _manifest_entries(manifest_payload, "source manifest")
    if len(manifest_entries) != SOURCE_MANIFEST_ENTRY_COUNT:
        raise StageAGateError("source manifest entry count changed")
    _workspace_exact(
        root,
        SOURCE_EVIDENCE_COMMIT,
        STAGE_B_APPENDIX_PATH,
        STAGE_B_APPENDIX_SHA256,
        "Stage-B appendix",
    )
    _workspace_exact(
        root,
        SOURCE_EVIDENCE_COMMIT,
        STAGE_B_REPORT_PATH,
        STAGE_B_REPORT_SHA256,
        "Stage-B report",
    )
    parents, accepted = _validate_stage_b_source(
        root, SOURCE_EVIDENCE_COMMIT, manifest_entries
    )
    _validate_budget(root)
    _validate_frozen_science(root, implementation_commit, execution_commit)
    runtime_blobs = validate_runtime_path_blobs(
        root, implementation_commit, execution_commit, runtime_paths
    )
    _validate_clean_tracked_code(root)
    return BCompletionGateInputs(
        source_evidence_commit=SOURCE_EVIDENCE_COMMIT,
        preregistration_commit=PREREGISTRATION_COMMIT,
        implementation_commit=implementation_commit,
        execution_commit=execution_commit,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_manifest_entry_count=SOURCE_MANIFEST_ENTRY_COUNT,
        accepted_record_count=accepted,
        stage_b_run_count=len(STAGE_B_RUN_IDS),
        parents=parents,
        budget_source_commit=BUDGET_SOURCE_COMMIT,
        budget_summary_sha256=BUDGET_SUMMARY_SHA256,
        budget_config_hash=BUDGET_CONFIG_HASH,
        frozen_science_blobs={
            path.as_posix(): blob for path, blob in FROZEN_SCIENCE_BLOBS.items()
        },
        runtime_path_blobs=runtime_blobs,
        clean_tracked_code=True,
    )
