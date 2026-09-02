"""Archive exploration run evidence with a verifiable integrity manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ArchiveRole = Literal[
    "baseline-classic",
    "baseline-random",
    "agent-gp",
    "smoke",
    "other",
]

ROLE_CHOICES: tuple[ArchiveRole, ...] = (
    "baseline-classic",
    "baseline-random",
    "agent-gp",
    "smoke",
    "other",
)
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EVIDENCE_FILES: tuple[str, str] = ("log.jsonl", "summary.json")


class ArchiveError(RuntimeError):
    """Raised when evidence cannot be archived without ambiguity."""


class RunSummary(BaseModel):
    """Subset of summary.json that must enter the manifest programmatically."""

    model_config = ConfigDict(extra="allow")

    run_id: str
    config_hash: str = Field(min_length=1)
    seed: int
    steps_completed: int = Field(ge=0)
    solver_mode_counts: dict[str, int]


class ManifestEntry(BaseModel):
    """One immutable-evidence record in the version-controlled manifest."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    role: ArchiveRole
    note: str
    config_hash: str
    seed: int
    steps_completed: int
    solver_mode_counts: dict[str, int]
    sha256: dict[str, str]
    archived_at: datetime
    overwritten: bool = False
    annotation: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_hashes(self) -> ManifestEntry:
        if set(self.sha256) != set(EVIDENCE_FILES):
            raise ValueError(f"sha256 must contain exactly {EVIDENCE_FILES}")
        for digest in self.sha256.values():
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("sha256 values must be lowercase SHA-256 digests")
        return self


class VerificationResult(BaseModel):
    """Integrity result for one manifest entry."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    ok: bool
    details: tuple[str, ...] = ()


def sha256_file(path: Path) -> str:
    """Hash a file without loading the complete evidence file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id) or run_id in {".", ".."}:
        raise ArchiveError(f"invalid run_id: {run_id!r}")


def _read_manifest(manifest_path: Path, *, required: bool) -> list[ManifestEntry]:
    if not manifest_path.is_file():
        if required:
            raise ArchiveError(f"manifest missing: {manifest_path}")
        return []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ArchiveError("manifest root must be a JSON array")
        entries = [ManifestEntry.model_validate(item) for item in payload]
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ArchiveError(f"invalid manifest: {error}") from error
    run_ids = [entry.run_id for entry in entries]
    if len(run_ids) != len(set(run_ids)):
        raise ArchiveError("manifest contains duplicate run_id entries")
    return entries


def _write_manifest(manifest_path: Path, entries: list[ManifestEntry]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(".json.tmp")
    payload: list[dict[str, object]] = []
    for entry in entries:
        item = entry.model_dump(mode="json")
        if not entry.annotation:
            item.pop("annotation")
        payload.append(item)
    temporary.write_bytes(
        (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8")
    )
    os.replace(temporary, manifest_path)


def annotate_run(
    run_id: str,
    annotation: str,
    *,
    artifacts_root: Path,
) -> ManifestEntry:
    """Append an audit annotation without changing archived evidence bytes."""

    _validate_run_id(run_id)
    normalized = annotation.strip()
    if not normalized:
        raise ArchiveError("annotation must not be empty")
    manifest_path = artifacts_root / "manifest.json"
    entries = _read_manifest(manifest_path, required=True)
    existing_index = next(
        (index for index, entry in enumerate(entries) if entry.run_id == run_id),
        None,
    )
    if existing_index is None:
        raise ArchiveError(f"run {run_id!r} is not present in the manifest")
    existing = entries[existing_index]
    updated = existing.model_copy(
        update={"annotation": (*existing.annotation, normalized)}
    )
    entries[existing_index] = updated
    _write_manifest(manifest_path, entries)
    return updated


def archive_run(
    run_id: str,
    role: ArchiveRole,
    note: str,
    *,
    runs_root: Path,
    artifacts_root: Path,
    force: bool = False,
    archived_at: datetime | None = None,
) -> ManifestEntry:
    """Copy one run into the evidence archive and atomically update its manifest."""

    _validate_run_id(run_id)
    source_directory = runs_root / run_id
    source_files = {name: source_directory / name for name in EVIDENCE_FILES}
    missing = [str(path) for path in source_files.values() if not path.is_file()]
    if missing:
        raise ArchiveError("source evidence missing: " + ", ".join(missing))

    try:
        summary = RunSummary.model_validate_json(
            source_files["summary.json"].read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as error:
        raise ArchiveError(f"invalid source summary: {error}") from error
    if summary.run_id != run_id:
        raise ArchiveError(
            f"summary run_id {summary.run_id!r} does not match source directory {run_id!r}"
        )

    manifest_path = artifacts_root / "manifest.json"
    entries = _read_manifest(manifest_path, required=False)
    existing_index = next(
        (index for index, entry in enumerate(entries) if entry.run_id == run_id),
        None,
    )
    target_directory = artifacts_root / run_id
    target_preexisted = existing_index is not None or target_directory.exists()
    if target_preexisted and not force:
        raise ArchiveError(
            f"run {run_id!r} is already archived; use --force for an explicit overwrite"
        )

    source_hashes = {name: sha256_file(path) for name, path in source_files.items()}
    target_directory.mkdir(parents=True, exist_ok=True)
    for name, source in source_files.items():
        shutil.copy2(source, target_directory / name)
    copied_hashes = {
        name: sha256_file(target_directory / name)
        for name in EVIDENCE_FILES
    }
    if copied_hashes != source_hashes:
        raise ArchiveError(f"copy verification failed for run {run_id!r}")

    entry = ManifestEntry(
        run_id=run_id,
        role=role,
        note=note,
        config_hash=summary.config_hash,
        seed=summary.seed,
        steps_completed=summary.steps_completed,
        solver_mode_counts=summary.solver_mode_counts,
        sha256=copied_hashes,
        archived_at=archived_at or datetime.now(UTC),
        overwritten=force and target_preexisted,
    )
    if existing_index is None:
        entries.append(entry)
    else:
        entries[existing_index] = entry
    _write_manifest(manifest_path, entries)
    return entry


def verify_archive(artifacts_root: Path) -> list[VerificationResult]:
    """Recompute every manifest digest and report missing or modified evidence."""

    entries = _read_manifest(artifacts_root / "manifest.json", required=True)
    results: list[VerificationResult] = []
    for entry in entries:
        details: list[str] = []
        for name in EVIDENCE_FILES:
            path = artifacts_root / entry.run_id / name
            if not path.is_file():
                details.append(f"{name} missing")
                continue
            actual = sha256_file(path)
            expected = entry.sha256[name]
            if actual != expected:
                details.append(
                    f"{name} sha256 expected={expected} actual={actual}"
                )
        results.append(
            VerificationResult(
                run_id=entry.run_id,
                ok=not details,
                details=tuple(details),
            )
        )
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--role", choices=ROLE_CHOICES)
    parser.add_argument("--note", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--annotate")
    return parser


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    """CLI entry point; returns a process-compatible exit code."""

    args = _parser().parse_args(argv)
    root = repo_root or Path(__file__).resolve().parents[1]
    artifacts_root = root / "artifacts" / "runs"
    try:
        if args.verify:
            if (
                args.run_id is not None
                or args.role is not None
                or args.force
                or args.annotate is not None
            ):
                raise ArchiveError("--verify cannot be combined with archive arguments")
            results = verify_archive(artifacts_root)
            for result in results:
                if result.ok:
                    print(f"{result.run_id}: OK")
                else:
                    print(f"{result.run_id}: MISMATCH ({'; '.join(result.details)})")
            return 0 if all(result.ok for result in results) else 1

        if args.annotate is not None:
            if args.run_id is None or args.role is not None or args.force:
                raise ArchiveError(
                    "--annotate requires run_id and cannot be combined with archive arguments"
                )
            entry = annotate_run(
                args.run_id,
                args.annotate,
                artifacts_root=artifacts_root,
            )
            print(f"{entry.run_id}: ANNOTATED")
            return 0

        if args.run_id is None or args.role is None:
            raise ArchiveError("run_id and --role are required when archiving")
        entry = archive_run(
            args.run_id,
            cast(ArchiveRole, args.role),
            args.note,
            runs_root=root / "runs",
            artifacts_root=artifacts_root,
            force=args.force,
        )
        print(f"{entry.run_id}: ARCHIVED role={entry.role}")
        return 0
    except ArchiveError as error:
        print(f"archive_run: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
