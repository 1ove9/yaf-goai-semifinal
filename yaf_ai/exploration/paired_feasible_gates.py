"""Git and evidence gates for the solver-free feasibility Stage A."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

V1_PREREGISTRATION_COMMIT = "dcf9b28797ec0a97ba9b05ed9f8b1710d447b28c"
V1_PREREGISTRATION_DOCUMENT_SHA256 = "d5e5c02f9ad86cd09015d1a400af7f0b8aae31a9b7cba2ed3ff35438d6dd47f9"
V2_PREREGISTRATION_COMMIT = "e5fab578288f9660a80fa7211b130b5c2fdd63bb"
V2_PREREGISTRATION_DOCUMENT_SHA256 = "b56890d5272a37afc805ef627d6dd37ab1aa47ac46d99e3812bdf190da735a27"
SOURCE_COMMIT = "66a4325d9bc07ca97a8ec4e6ddf86b2854663a45"
SOURCE_MANIFEST_SHA256 = (
    "f747e908ffadbdb7eb3a6eb8ed4809dc21ffcaec63bb97a533f526c5a6913674"
)
SOURCE_MANIFEST_ENTRY_COUNT = 224
R2_APPENDIX_SHA256 = (
    "42ff2d13b5dbb09680a47dd90dfcca83a093811a1a1db950c24557c1a7f4156d"
)
R2_REPORT_SHA256 = (
    "d9abefb0dd4c0e5e709552bd22a36d0bf8f15daf7093e33a38dccbe4ad85bdc0"
)
BUDGET_SOURCE_COMMIT = "253090b80df23184cb8521cbbe77af1e38a9b734"
BUDGET_SUMMARY_SHA256 = (
    "b0a7f612e98064a3cf415731d89a917872fbc3931ee6d1f0116d8de8aaff6138"
)
BUDGET_CONFIG_HASH = (
    "d618134588d0db607e21638fdffed4ebff3627a669d281b3dfef456bafc43f92"
)

MANIFEST_PATH = Path("artifacts/runs/manifest.json")
R2_APPENDIX_PATH = Path(
    "artifacts/analysis/semifinal-paired-r2-robust-hunt/appendix.json"
)
R2_REPORT_PATH = Path(
    "artifacts/analysis/semifinal-paired-r2-robust-hunt/report.md"
)
BUDGET_SUMMARY_PATH = Path(
    "artifacts/runs/semifinal-paired-budget-preflight/summary.json"
)
R2_RUN_IDS = tuple(
    f"semifinal-paired-r2-es-warm-s{seed}"
    for seed in (101, 202, 303, 404, 505)
)

V1_PREREGISTRATION_PATH = Path(
    "docs/semifinal-feasibility-stratified-study-preregistration.md"
)
V2_PREREGISTRATION_PATH = Path(
    "docs/semifinal-feasibility-stratified-exact-v2-preregistration.md"
)

FROZEN_SCIENCE_BLOBS: dict[Path, str] = {
    Path("yaf_ai/exploration/paired_runner.py"): "d2ece9096be6daa86de6b281bb64a8b1150c782e",
    Path("yaf_ai/exploration/paired_solver.py"): "96efa9fe3e755fbca9b31315d96a330bef7291b9",
    Path("yaf_ai/exploration/paired_meander.py"): "98fd67154d5f6a512fdf46b99da1fc273ba8eced",
    Path("yaf_ai/exploration/paired_agents.py"): "0b8b8046611bca0fd2e0c0649277e5594f439f99",
    Path("yaf_ai/exploration/day65_batch.py"): "5944f5c2f9c892aa0a6860b2ef443f914f6baecc",
}

_FULL_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class StageAGateError(RuntimeError):
    """Raised before Stage A when committed provenance cannot be proven."""


class StageAProvenance(BaseModel):
    """Validated immutable provenance written into the Stage-A summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    study_id: str
    spec_revision: str
    mapping_version: str
    superseded_v1_preregistration_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    superseded_v1_preregistration_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    v2_preregistration_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    v2_preregistration_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_entry_count: int
    r2_appendix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    r2_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    budget_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_science_blobs: dict[str, str]
    clean_code_tree: bool


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
        raise StageAGateError(f"cannot execute Git gate: {error}") from error
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", errors="replace").strip()
        raise StageAGateError(f"Git gate failed for {arguments!r}: {message}")
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
        raise StageAGateError(f"cannot execute Git ancestry gate: {error}") from error
    if process.returncode != 0:
        raise StageAGateError(
            f"required commit {ancestor} is not an ancestor of {descendant}"
        )


def _workspace_exact(
    repo_root: Path,
    commit: str,
    path: Path,
    expected_sha256: str,
    label: str,
) -> bytes:
    committed = _git_blob(repo_root, commit, path)
    try:
        current = (repo_root / path).read_bytes()
    except OSError as error:
        raise StageAGateError(f"cannot read {label}: {error}") from error
    if current != committed:
        raise StageAGateError(f"{label} differs from committed evidence")
    if _sha256(current) != expected_sha256:
        raise StageAGateError(f"{label} SHA-256 differs from preregistration")
    return current


def _manifest_entries(payload: bytes, label: str) -> list[dict[str, object]]:
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StageAGateError(f"cannot parse {label}: {error}") from error
    if not isinstance(parsed, list):
        raise StageAGateError(f"{label} is not a JSON array")
    entries: list[dict[str, object]] = []
    run_ids: list[str] = []
    for entry in parsed:
        if not isinstance(entry, dict) or not isinstance(entry.get("run_id"), str):
            raise StageAGateError(f"{label} contains an invalid manifest entry")
        run_ids.append(entry["run_id"])
        entries.append(entry)
    if len(run_ids) != len(set(run_ids)):
        raise StageAGateError(f"{label} contains duplicate run IDs")
    return entries


def _validate_manifest(repo_root: Path) -> None:
    pinned = _git_blob(repo_root, SOURCE_COMMIT, MANIFEST_PATH)
    if _sha256(pinned) != SOURCE_MANIFEST_SHA256:
        raise StageAGateError("source manifest SHA-256 changed")
    try:
        current = (repo_root / MANIFEST_PATH).read_bytes()
    except OSError as error:
        raise StageAGateError(f"cannot read current manifest: {error}") from error
    pinned_entries = _manifest_entries(pinned, "source manifest")
    current_entries = _manifest_entries(current, "current manifest")
    if len(pinned_entries) != SOURCE_MANIFEST_ENTRY_COUNT:
        raise StageAGateError("source manifest entry count changed")
    if len(current_entries) < SOURCE_MANIFEST_ENTRY_COUNT:
        raise StageAGateError("current manifest lost pinned entries")
    if current_entries[:SOURCE_MANIFEST_ENTRY_COUNT] != pinned_entries:
        raise StageAGateError("current manifest is not an append-only source successor")


def _manifest_index(
    entries: list[dict[str, object]],
    label: str,
) -> dict[str, dict[str, object]]:
    index = {str(entry["run_id"]): entry for entry in entries}
    if len(index) != len(entries):
        raise StageAGateError(f"{label} contains duplicate run IDs")
    return index


def _validate_r2_run_files(repo_root: Path) -> None:
    source_manifest = _manifest_index(
        _manifest_entries(
            _git_blob(repo_root, SOURCE_COMMIT, MANIFEST_PATH),
            "source manifest",
        ),
        "source manifest",
    )
    try:
        current_manifest = _manifest_index(
            _manifest_entries(
                (repo_root / MANIFEST_PATH).read_bytes(),
                "current manifest",
            ),
            "current manifest",
        )
    except OSError as error:
        raise StageAGateError(f"cannot read current manifest: {error}") from error

    for run_id in R2_RUN_IDS:
        try:
            source_entry = source_manifest[run_id]
            current_entry = current_manifest[run_id]
        except KeyError as error:
            raise StageAGateError(f"R2 manifest entry is missing: {run_id}") from error
        if source_entry != current_entry:
            raise StageAGateError(f"R2 manifest entry changed: {run_id}")
        hashes = source_entry.get("sha256")
        if not isinstance(hashes, dict):
            raise StageAGateError(f"R2 manifest SHA map is invalid: {run_id}")
        for filename in ("log.jsonl", "summary.json"):
            expected = hashes.get(filename)
            if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
                raise StageAGateError(
                    f"R2 manifest {filename} SHA is invalid: {run_id}"
                )
            path = Path("artifacts/runs") / run_id / filename
            source_bytes = _git_blob(repo_root, SOURCE_COMMIT, path)
            try:
                workspace_bytes = (repo_root / path).read_bytes()
            except OSError as error:
                raise StageAGateError(
                    f"cannot read R2 {filename} for {run_id}: {error}"
                ) from error
            if workspace_bytes != source_bytes:
                raise StageAGateError(
                    f"R2 {filename} differs from source commit: {run_id}"
                )
            if _sha256(source_bytes) != expected:
                raise StageAGateError(
                    f"R2 {filename} SHA differs from manifest: {run_id}"
                )

def _validate_budget(repo_root: Path) -> None:
    payload = _workspace_exact(
        repo_root,
        BUDGET_SOURCE_COMMIT,
        BUDGET_SUMMARY_PATH,
        BUDGET_SUMMARY_SHA256,
        "budget summary",
    )
    try:
        summary = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StageAGateError(f"cannot parse budget summary: {error}") from error
    expected = (
        isinstance(summary, dict),
        summary.get("result_status") == "completed" if isinstance(summary, dict) else False,
        summary.get("raw_budget") == 907 if isinstance(summary, dict) else False,
        summary.get("budget") == 300 if isinstance(summary, dict) else False,
        summary.get("config_hash") == BUDGET_CONFIG_HASH if isinstance(summary, dict) else False,
        summary.get("t_pair_p95_seconds") == 3.7018278000032296 if isinstance(summary, dict) else False,
        summary.get("p95_method") == "higher" if isinstance(summary, dict) else False,
        summary.get("parallel_workers") == 1 if isinstance(summary, dict) else False,
    )
    if not all(expected):
        raise StageAGateError("budget summary fields differ from preregistration")


def _validate_frozen_science(repo_root: Path, head: str) -> None:
    for path, expected_blob in FROZEN_SCIENCE_BLOBS.items():
        source_blob = _git(
            repo_root, "rev-parse", f"{SOURCE_COMMIT}:{path.as_posix()}"
        ).decode("ascii").strip()
        head_blob = _git(
            repo_root, "rev-parse", f"{head}:{path.as_posix()}"
        ).decode("ascii").strip()
        workspace_blob = _git(
            repo_root,
            "hash-object",
            f"--path={path.as_posix()}",
            path.as_posix(),
        ).decode("ascii").strip()
        if source_blob != expected_blob or head_blob != expected_blob:
            raise StageAGateError(f"frozen science blob changed: {path}")
        if workspace_blob != expected_blob:
            raise StageAGateError(f"workspace science bytes changed: {path}")


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
        raise StageAGateError("Stage-A code tree is not clean at implementation HEAD")


def validate_stage_a_provenance(repo_root: Path) -> StageAProvenance:
    """Validate every preregistered evidence gate before Stage-A computation."""

    root = repo_root.resolve()
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if _FULL_COMMIT.fullmatch(head) is None:
        raise StageAGateError("implementation HEAD is not a full commit hash")
    for ancestor in (
        SOURCE_COMMIT,
        BUDGET_SOURCE_COMMIT,
        V1_PREREGISTRATION_COMMIT,
        V2_PREREGISTRATION_COMMIT,
    ):
        _require_ancestor(root, ancestor, head)

    _workspace_exact(
        root,
        V1_PREREGISTRATION_COMMIT,
        V1_PREREGISTRATION_PATH,
        V1_PREREGISTRATION_DOCUMENT_SHA256,
        "superseded v1 preregistration",
    )
    _workspace_exact(
        root,
        V2_PREREGISTRATION_COMMIT,
        V2_PREREGISTRATION_PATH,
        V2_PREREGISTRATION_DOCUMENT_SHA256,
        "v2 preregistration",
    )

    _validate_manifest(root)
    _validate_r2_run_files(root)
    _workspace_exact(
        root, SOURCE_COMMIT, R2_APPENDIX_PATH, R2_APPENDIX_SHA256, "R2 appendix"
    )
    _workspace_exact(root, SOURCE_COMMIT, R2_REPORT_PATH, R2_REPORT_SHA256, "R2 report")
    _validate_budget(root)
    _validate_frozen_science(root, head)
    _validate_clean_code_tree(root)
    return StageAProvenance(
        study_id="semifinal-paired-feasibility-stratified-exact-v2",
        spec_revision="2.0-exact-nominal-support",
        mapping_version="conditional-exact-feasible-turn-v2",
        superseded_v1_preregistration_commit=V1_PREREGISTRATION_COMMIT,
        superseded_v1_preregistration_document_sha256=V1_PREREGISTRATION_DOCUMENT_SHA256,
        v2_preregistration_commit=V2_PREREGISTRATION_COMMIT,
        v2_preregistration_document_sha256=V2_PREREGISTRATION_DOCUMENT_SHA256,
        source_commit=SOURCE_COMMIT,
        implementation_commit=head,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_manifest_entry_count=SOURCE_MANIFEST_ENTRY_COUNT,
        r2_appendix_sha256=R2_APPENDIX_SHA256,
        r2_report_sha256=R2_REPORT_SHA256,
        budget_source_commit=BUDGET_SOURCE_COMMIT,
        budget_summary_sha256=BUDGET_SUMMARY_SHA256,
        budget_config_hash=BUDGET_CONFIG_HASH,
        frozen_science_blobs={
            path.as_posix(): blob for path, blob in FROZEN_SCIENCE_BLOBS.items()
        },
        clean_code_tree=True,
    )
