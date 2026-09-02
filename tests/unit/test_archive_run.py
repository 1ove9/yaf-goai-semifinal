"""Tests for the exploration evidence archiver."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.archive_run import (
    ArchiveError,
    ManifestEntry,
    annotate_run,
    archive_run,
    main,
    sha256_file,
    verify_archive,
)


def _fake_run(root: Path, run_id: str = "run-001") -> Path:
    run_directory = root / "runs" / run_id
    run_directory.mkdir(parents=True)
    (run_directory / "log.jsonl").write_text(
        '{"step_index":0,"solver_mode":"subprocess"}\n',
        encoding="utf-8",
    )
    (run_directory / "summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "config_hash": "a" * 64,
                "seed": 42,
                "steps_completed": 1,
                "solver_mode_counts": {"subprocess": 1},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return run_directory


def _manifest(root: Path) -> list[ManifestEntry]:
    payload = json.loads(
        (root / "artifacts" / "runs" / "manifest.json").read_text(encoding="utf-8")
    )
    return [ManifestEntry.model_validate(item) for item in payload]


def test_archive_creates_manifest_hashes_without_touching_source(tmp_path: Path) -> None:
    source = _fake_run(tmp_path)
    original = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in source.iterdir()
    }
    archived_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

    entry = archive_run(
        "run-001",
        "baseline-random",
        "matched baseline",
        runs_root=tmp_path / "runs",
        artifacts_root=tmp_path / "artifacts" / "runs",
        archived_at=archived_at,
    )

    target = tmp_path / "artifacts" / "runs" / "run-001"
    assert entry.config_hash == "a" * 64
    assert entry.seed == 42
    assert entry.steps_completed == 1
    assert entry.solver_mode_counts == {"subprocess": 1}
    assert entry.sha256 == {
        "log.jsonl": sha256_file(target / "log.jsonl"),
        "summary.json": sha256_file(target / "summary.json"),
    }
    assert entry.archived_at == archived_at
    assert entry.overwritten is False
    assert _manifest(tmp_path) == [entry]
    manifest_path = tmp_path / "artifacts" / "runs" / "manifest.json"
    assert b"\r" not in manifest_path.read_bytes()
    for path in source.iterdir():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original[path.name]


def test_duplicate_fails_and_force_overwrites_with_audit_flag(tmp_path: Path) -> None:
    source = _fake_run(tmp_path)
    kwargs = {
        "runs_root": tmp_path / "runs",
        "artifacts_root": tmp_path / "artifacts" / "runs",
    }
    archive_run("run-001", "other", "first", **kwargs)

    with pytest.raises(ArchiveError, match="already archived"):
        archive_run("run-001", "other", "duplicate", **kwargs)

    (source / "log.jsonl").write_text(
        '{"step_index":0,"solver_mode":"subprocess","repeated":true}\n',
        encoding="utf-8",
    )
    overwritten = archive_run(
        "run-001",
        "smoke",
        "explicit replacement",
        force=True,
        **kwargs,
    )

    entries = _manifest(tmp_path)
    assert entries == [overwritten]
    assert overwritten.overwritten is True
    assert overwritten.role == "smoke"
    assert overwritten.note == "explicit replacement"
    assert overwritten.sha256["log.jsonl"] == sha256_file(source / "log.jsonl")


def test_verify_returns_nonzero_after_tampering(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_run(tmp_path)
    archive_run(
        "run-001",
        "agent-gp",
        "",
        runs_root=tmp_path / "runs",
        artifacts_root=tmp_path / "artifacts" / "runs",
    )
    archived_log = tmp_path / "artifacts" / "runs" / "run-001" / "log.jsonl"
    archived_log.write_text("tampered\n", encoding="utf-8")

    results = verify_archive(tmp_path / "artifacts" / "runs")
    assert len(results) == 1
    assert results[0].ok is False
    assert "log.jsonl sha256" in results[0].details[0]
    assert main(["--verify"], repo_root=tmp_path) == 1
    assert "run-001: MISMATCH" in capsys.readouterr().out


def test_missing_source_file_is_rejected(tmp_path: Path) -> None:
    source = _fake_run(tmp_path)
    (source / "summary.json").unlink()

    with pytest.raises(ArchiveError, match="source evidence missing"):
        archive_run(
            "run-001",
            "other",
            "",
            runs_root=tmp_path / "runs",
            artifacts_root=tmp_path / "artifacts" / "runs",
        )


def test_annotation_appends_without_changing_evidence(tmp_path: Path) -> None:
    _fake_run(tmp_path)
    artifacts_root = tmp_path / "artifacts" / "runs"
    archive_run(
        "run-001",
        "other",
        "original note",
        runs_root=tmp_path / "runs",
        artifacts_root=artifacts_root,
    )
    evidence = {
        name: (artifacts_root / "run-001" / name).read_bytes()
        for name in ("log.jsonl", "summary.json")
    }

    first = annotate_run(
        "run-001", "first audit finding", artifacts_root=artifacts_root
    )
    second = annotate_run(
        "run-001", "second audit finding", artifacts_root=artifacts_root
    )

    assert first.annotation == ("first audit finding",)
    assert second.annotation == ("first audit finding", "second audit finding")
    assert second.note == "original note"
    assert verify_archive(artifacts_root)[0].ok is True
    for name, original in evidence.items():
        assert (artifacts_root / "run-001" / name).read_bytes() == original


def test_annotate_cli_rejects_unknown_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts_root = tmp_path / "artifacts" / "runs"
    artifacts_root.mkdir(parents=True)
    (artifacts_root / "manifest.json").write_text("[]\n", encoding="utf-8")

    assert main(["missing", "--annotate", "retracted"], repo_root=tmp_path) == 2
    assert "not present in the manifest" in capsys.readouterr().err
