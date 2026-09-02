"""Run and archive the preregistered Day 6 dimensions and references."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from yaf_ai.exploration.day6 import execute_preflight_and_references


def _archived(repo_root: Path) -> set[str]:
    path = repo_root / "artifacts" / "runs" / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["run_id"]) for item in payload}


def _archive(repo_root: Path, run_id: str, role: str, note: str) -> None:
    if run_id in _archived(repo_root):
        return
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "archive_run.py"),
            run_id,
            "--role",
            role,
            "--note",
            note,
        ],
        cwd=repo_root,
        check=True,
    )


async def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    result = await execute_preflight_and_references(repo_root)
    for probe in result.probes:
        _archive(
            repo_root,
            probe.run_id,
            "other",
            f"batch=day6-freeform dimension-preflight N={probe.node_count} seed={probe.seed}",
        )
    assert result.ocfd is not None
    assert result.straight is not None
    _archive(
        repo_root,
        result.ocfd.run_id,
        "baseline-classic",
        "batch=day6-freeform preregistered 20x20 OCFD reference scan",
    )
    _archive(
        repo_root,
        result.straight.run_id,
        "baseline-classic",
        "batch=day6-freeform 2.45 GHz tuned straight-dipole control",
    )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
